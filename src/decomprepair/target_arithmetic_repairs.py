"""Source shapes for measured arithmetic and loop-control differences."""

import re

from .compiler_phase_repairs import fresh
from .csource import find
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, integer, plain_repair_view
from .measured_control_repairs import automatic_integers
from .operand_lifetime_repairs import FLOAT, _escaped, _in_scope, _plain_expression, _typed_locals, _visible
from .pattern_repairs import close
from .target_memory_repairs import WORD, _statement

EXIT_RESET = 'loop_exit_counter_reset'
MULT_HIGH = 'signed_multiply_high_word'
ACCUMULATE = 'stepwise_float_accumulator'
TRIM = 'top_tested_byte_trim'
PACKED_OPCODE = 'packed_field_opcode_staging'


def exit_reset(source, name, header, bounds, callees):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    types = _typed_locals(part,WORD)
    out = []
    for loop in re.compile(r'\bdo\s*{').finditer(part.clean,part.opening+1,part.end-1):
        if not _statement(part,loop.start()):
            continue
        end = close(part.clean,loop.end()-1,'{','}')
        if not end:
            continue
        tail = re.match(rf'\s*while\s*\(\s*(?P<count>{IDENT})\s*<\s*(?P<bound>{NUMBER})\s*\)\s*;\s*'
                        rf'(?P<reset>(?P<var>{IDENT})\s*=\s*0[uU]?\s*;)\s*(?P<call>{IDENT})\s*\(',
                        part.clean[end:part.end])
        if not tail or integer(tail['bound']) not in bounds or tail['call'] not in callees:
            continue
        count,var = tail['count'],tail['var']
        if re.search(rf'\bvolatile\b[^;{{}}\n]*\b(?:{count}|{var})\b|#\s*define\s+[^\n]*\b(?:{count}|{var})\b',context):
            continue
        if not all(n in types and _in_scope(part,types[n][1],loop.start()) and not _escaped(part.body,n)
                   for n in (count,var)):
            continue
        body = part.clean[loop.end():end-1]
        if re.search(r'\b(?:break|continue|return|goto)\b|[;{}]\s*\w+\s*:',body):
            continue
        if not re.search(rf'\b{count}\s*(?:\+\+|\+=\s*1[uU]?\b)',body):
            continue
        if count!=var and re.search(rf'\b{var}\b',body):
            continue
        reset = f"if ({count} >= {tail['bound']}) {{ {var} = 0; break; }}"
        out.append((EXIT_RESET,edit(source,[(end-1,end-1,' '+reset+' '),
                                           (end+tail.start('reset'),end+tail.end('reset'),'')])))
        if len(out)==2:
            break
    return out


def multiply_high(source, name, header):
    part = plain_repair_view(source,name,header)
    if not part:
        return []
    wide = r'(?:s64|long\s+long|signed\s+long\s+long)'
    signed = r'(?:s32|int|signed\s+int)'
    # Match the signed 32x32 product and its signed high-word extraction.
    # The union is specific to the compiler and byte order proved by the host.
    expression = re.compile(rf'\(\s*\(\s*\(\s*{wide}\s*\)\s*(?P<a>{IDENT})\s*\*\s*'
                            rf'(?P<b>{IDENT}|{NUMBER})\s*\)\s*>>\s*32[uU]?\s*\)')
    signed_vars = set(n for n,(typ,_) in _typed_locals(part,WORD).items() if re.fullmatch(signed,typ))
    signature = part.clean[find(source,name)[0]:part.opening]
    signed_vars.update(re.findall(rf'\b{signed}\s+({IDENT})\s*(?=[,)])',signature))
    out = []
    for hit in expression.finditer(part.clean,part.opening+1,part.end-1):
        if hit['a'] not in signed_vars:
            continue
        if hit['b'] not in signed_vars and (not re.fullmatch(NUMBER,hit['b'])
                or integer(hit['b'])>0x7fffffff or hit['b'].lower().endswith(('u','l'))):
            continue
        preceding = max(part.clean.rfind(c,part.opening,hit.start()) for c in ';{}')+1
        statement = part.clean[preceding:hit.start()]
        if not re.fullmatch(rf'\s*(?:return\s+|{IDENT}\s*=\s*)(?:\(\s*{signed}\s*\)\s*)?',statement):
            continue
        stop = re.match(r'\s*;',part.clean[hit.end():part.end])
        if not stop:
            continue
        # A standalone signed word result is required, so the expression
        # cannot have influenced conversions or promotion in a larger tree.
        lhs = re.match(rf'\s*({IDENT})\s*=',statement)
        if lhs and lhs[1] not in signed_vars:
            continue
        if not lhs and not re.match(rf'\s*(?:(?:static|inline)\s+)*{signed}\s+{name}\b',signature):
            continue
        token = fresh(source,header,'repair_product')
        declaration = (f'{{ union {{ long long whole; struct {{ int high; unsigned int low; }} words; }} {token}; '
                       f'{token}.whole = (long long){hit["a"]} * {hit["b"]}; ')
        end = hit.end()+stop.end()
        out.append((MULT_HIGH,edit(source,[(preceding,preceding,declaration),(hit.start(),hit.end(),token+'.words.high'),
                                           (end,end,' }')])))
        if len(out)==2:
            break
    return out


def _python_sum_terms(expression):
    depth = 0
    last = 0
    terms = []
    for i,ch in enumerate(expression):
        if ch=='(':
            depth += 1
        elif ch==')':
            depth -= 1
        elif ch=='+' and depth==0:
            terms.append(expression[last:i].strip())
            last = i+1
    return [*terms,expression[last:].strip()]


_sum_terms = _python_sum_terms
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _sum_terms(expression):
        return [term.strip() for term in _scan.top_pieces(expression, '+', 1)]


def float_accumulator(source, name, header, precision):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    if re.search(r'\bvolatile\b',context):
        return []
    locals_ = _typed_locals(part,FLOAT)
    initialized = {}
    for decl in re.compile(rf'\b({FLOAT})\s+({IDENT})\s*=\s*[^;{{}}]+;').finditer(part.clean,part.opening+1,part.end-1):
        if _statement(part,decl.start()):
            initialized[decl[2]] = (decl[1],decl.start())
    types = {key:typ for key,(typ,_) in (locals_ | initialized).items()}
    signature = part.clean[find(source,name)[0]:part.opening]
    types.update({n:t for t,n in re.findall(rf'\b({FLOAT})\s+({IDENT})\s*(?=[,)])',signature)})
    shape = re.compile(rf'\b(?:(?P<type>{FLOAT})\s+)?(?P<var>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}]+);')
    out = []
    for sum_ in shape.finditer(part.clean,part.opening+1,part.end-1):
        var = sum_['var']
        typ = sum_['type'] or types.get(var)
        width = 'd' if typ in {'double','f64'} else 's' if typ else None
        if width not in precision or not _statement(part,sum_.start()) or _escaped(part.body,var):
            continue
        if not sum_['type'] and (var not in locals_ or not _in_scope(part,locals_[var][1],sum_.start())):
            continue
        expression = sum_['expr']
        call = re.fullmatch(rf'({IDENT})\s*\((.*)\)',expression,re.S)
        if call:
            prototypes = {(ret,arg) for ret,arg in re.findall(
                rf'\b({FLOAT})\s+{call[1]}\s*\(\s*({FLOAT})(?:\s+{IDENT})?\s*\)\s*;',context)}
            if prototypes!={(typ,typ)}:
                continue
            expression = call[2]
        terms = _sum_terms(expression)
        if not 3<=len(terms)<=5 or not all(_plain_expression(term,context) for term in terms):
            continue
        if any(not re.fullmatch(rf'\(?\s*{IDENT}(?:\s*(?:->|\.)\s*{IDENT})?(?:\s*\*\s*{IDENT}(?:\s*(?:->|\.)\s*{IDENT})?)?\s*\)?',
                                t) for t in terms):
            continue
        if any(re.search(rf'\b{var}\b',term) for term in terms[1:]):
            continue
        # Match simple typed terms. Member terms have explicit, unambiguous
        # float declarations in the visible source or context.
        if any((types.get(n) not in {typ,'float' if typ=='f32' else 'f32' if typ=='float'
                                    else 'double' if typ=='f64' else 'f64'})
               for term in terms for n in re.findall(rf'(?<![.>\w])({IDENT})(?![\w]|\s*(?:->|\.))',term)):
            continue
        if any(initialized[n][1]>=sum_.start() or not _in_scope(part,initialized[n][1],sum_.start())
               for term in terms for n in re.findall(IDENT,term) if n in initialized):
            continue
        members = [m for term in terms for m in re.findall(r'(?:->|\.)\s*('+IDENT+')',term)]
        if any(not re.search(rf'\b{typ}\s+{m}\s*;',context) for m in members):
            continue
        definition = f'{typ} ' if sum_['type'] else ''
        changed = f"{definition}{var} = {terms[0]}; "+' '.join(f'{var} += {term};' for term in terms[1:])
        if call:
            changed += f' {var} = {call[1]}({var});'
        edits = [(sum_.start(),sum_.end(),changed)]
        # Also retain a directly consumed final operation in that same local,
        # when its result and the return type use exactly the same precision.
        tail = re.match(rf'\s*return\s+{var}\s*([*/])\s*({IDENT})\s*;',part.clean[sum_.end():part.end])
        if tail and types.get(tail[2])==typ and re.match(rf'\s*(?:static\s+)?{typ}\s+{name}\b',signature):
            start = sum_.end()+tail.start()
            out.append((ACCUMULATE,edit(source,[*edits,(start,sum_.end()+tail.end(),
                       f' {var} {tail[1]}= {tail[2]}; return {var};')])))
        out.append((ACCUMULATE,edit(source,edits)))
        if len(out)>=4:
            return out[:4]
    return out


def packed_opcode(source, name, header, constants):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    types = _typed_locals(part,WORD)
    out = []
    use = re.compile(rf'=\s*(?P<x>{IDENT})\s*\|\s*\(\s*(?P<y>{IDENT})\s*\|\s*(?P<c>{NUMBER})\s*\)\s*;')
    for hit in use.finditer(part.clean,part.opening+1,part.end-1):
        constant,mask = next(((v,m) for v,m in constants if v==integer(hit['c'])),(None,None))
        x,y = hit['x'],hit['y']
        if constant is None or x==y or y not in types or not _in_scope(part,types[y][1],hit.start()):
            continue
        if _escaped(part.body,y) or re.search(rf'\bvolatile\b[^;{{}}\n]*\b{y}\b|#\s*define\s+[^\n]*\b{y}\b',context):
            continue
        start = max(types[y][1],hit.start()-600)
        setups = list(re.compile(rf'\b{y}\s*=(?!=)\s*(?P<expr>[^;{{}}]+);').finditer(part.clean,start,hit.start()))
        if not setups:
            continue
        setup = setups[-1]
        source_mask = re.search(rf'(?<!&) & \s* ({NUMBER}) \s* \)*\s*$',setup['expr'],re.X)
        if not source_mask or integer(source_mask[1])!=mask or not _statement(part,setup.start()):
            continue
        if re.search(rf'\b{y}\b|[{{}}:]|\bgoto\b',part.clean[setup.end():hit.start()]):
            continue
        if re.search(rf'\b{y}\b',part.clean[hit.end():part.end]):
            continue
        expr = source[setup.start('expr'):setup.end('expr')]
        out.append((PACKED_OPCODE,edit(source,[
            (*setup.span('expr'),f'({expr}) | {hit["c"]}'),
            (hit.start('x'),hit.end(),f'{x} | {y};'),
        ])))
        if len(out)==2:
            break
    return out


def top_tested_trim(source, name, header, pads):
    data = _visible(source,name,header)
    if not data:
        return []
    part,context = data
    if re.search(r'\bvolatile\b',part.body):
        return []
    known = automatic_integers(part,name) | set(_typed_locals(part,INTEGER))
    # The masked cursor form duplicates the zero check and byte remasking.
    # Restrict it to the full trim loop with no other effects.
    repeated = re.compile(
        rf'if\s*\(\s*(?P<seed>{IDENT})\s*!=\s*0\s*\)\s*{{\s*'
        rf'(?P<ptr>{IDENT})\s*=\s*(?P<low>{IDENT})\s*\+\s*(?P<src>{IDENT})\s*;\s*'
        rf'for\s*\(\s*;\s*;\s*\)\s*{{\s*(?P=low)\s*=\s*(?P<count>{IDENT})\s*&\s*(?:0[xX][fF]{{2}}|255)\s*;\s*'
        rf'if\s*\(\s*(?P<load>[^;{{}}]+?)\s*==\s*(?P<pad>{NUMBER})\s*\)\s*{{\s*'
        rf'(?P=count)\s*-=\s*1\s*;\s*(?P=low)\s*=\s*(?P=count)\s*&\s*(?:0[xX][fF]{{2}}|255)\s*;\s*'
        rf'(?P=ptr)\s*=\s*(?P=low)\s*\+\s*(?P=src)\s*;\s*'
        rf'if\s*\(\s*(?P=low)\s*==\s*0\s*\)\s*{{\s*(?P=low)\s*=\s*(?P=count)\s*&\s*(?:0[xX][fF]{{2}}|255)\s*;\s*}}\s*'
        r'else\s*{\s*continue\s*;\s*}\s*}\s*break\s*;\s*}\s*}')
    out = []
    for hit in repeated.finditer(part.clean,part.opening+1,part.end-1):
        seed,low,count,ptr,src = (hit[g] for g in ('seed','low','count','ptr','src'))
        if not _statement(part,hit.start()) or integer(hit['pad']) not in pads or count==low or not {seed,low,count}<=known:
            continue
        if any(_escaped(part.body,n) for n in (ptr,src,count,low)) or re.search(rf'\b{ptr}\b',part.clean[hit.end():part.end]):
            continue
        init = rf'\b{seed}\s*=\s*{count}\s*&\s*(?:0[xX][fF]{{2}}|255)\s*;'
        prefix = part.clean[max(part.opening+1,hit.start()-260):hit.start()]
        found = list(re.finditer(init,prefix))
        if not found or not re.search(rf'\b{low}\s*=\s*{count}\s*&\s*(?:0[xX][fF]{{2}}|255)\s*;\s*$',prefix):
            continue
        if re.search(rf'\b{count}\s*(?:=(?!=)|\+\+|--|[+-]=)|[{{}}:]|\bgoto\b',prefix[found[-1].end():]):
            continue
        cast = re.fullmatch(rf'\*\s*\(\s*(?P<type>s8|u8|char|signed\s+char|unsigned\s+char)\s*\*\s*\)'
                            rf'\s*\(\s*{ptr}\s*-\s*1\s*\)',hit['load'])
        macro = re.fullmatch(rf'M2C_FIELD\(\s*{ptr}\s*,\s*(?P<type>s8|u8|char)\s*\*\s*,\s*-1\s*\)',hit['load'])
        if not cast and not macro:
            continue
        if macro and not re.search(r'#\s*define\s+M2C_FIELD\((\w+),\s*(\w+),\s*(\w+)\)\s+'
                                   r'\(\*\(\2\)\(\((?:s8|char)\s*\*\)\(\1\)\s*\+\s*\(\3\)\)\)',context):
            continue
        kind = (cast or macro)['type']
        out.append((TRIM,edit(source,[(hit.start(),hit.end(),
            f"while ((unsigned char){count} && (({kind} *){src})[(unsigned char){count} - 1] == {hit['pad']}) {{ --{count}; }} "
            f"{low} = (unsigned char){count};")])))
        if len(out)==2:
            break
    return out
