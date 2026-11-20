"""Source candidates for measured memory scheduling and control-flow differences."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, integer
from .operand_lifetime_repairs import _escaped, _in_scope, _visible
from .pattern_repairs import close
from .target_conversion_order_repairs import F32, SIGNED, UNSIGNED, _context, _local, _refs, _result
from .target_edge_repairs import HALF
from .target_guard_width_repairs import _fields, _pointer_type
from .target_memory_repairs import WORD, _statement

FIELD = rf'{IDENT}\s*->\s*{IDENT}'
BYTE = r'(?:u8|char|unsigned\s+char|signed\s+char)'
S16 = r'(?:s16|(?:signed\s+)?short(?:\s+int)?)'


def middle_reload(source,name,header,witnesses):
    visible = _visible(source,name,header)
    if not visible:
        return []
    part,context = visible
    if re.search(r'\bgoto\b|\b(?:asm|__asm__)\b',part.body):
        return []
    for symbol,offset in sorted(witnesses):
        if not re.search(rf'\b(?:struct\s+)?{IDENT}\s*\*\s*volatile\s+{symbol}\s*;',context):
            continue
        shape = re.compile(
            rf'(?P<begin>(?P<p>{IDENT})\s*=\s*{symbol}\s*;)'
            rf'(?P<update>\s*\*\s*\(\s*(?P<t>{WORD})\s*\*\s*\)\s*'
            rf'\(\s*\(\s*{BYTE}\s*\*\s*\)\s*(?P=p)\s*\+\s*(?P<n>{NUMBER})\s*\)\s*\|=\s*{NUMBER}\s*;)'
            rf'(?=\s*(?P=p)\s*=\s*{symbol}\s*;)')
        for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
            p = hit['p']
            if (integer(hit['n'])!=offset or not _statement(part,hit.start()) or _escaped(part.body,p)
                    or not _pointer_type(part,p,find(source,name)[0])
                    or not re.search(rf'\b{p}\s*=\s*{symbol}\s*;',part.clean[part.opening+1:hit.start()])
                    or len(re.findall(rf'\b{symbol}\b',part.body))!=3
                    or re.search(rf'^\s*#\s*define\s+(?:{symbol}|{p})\b',context,re.M)):
                continue
            local = fresh(source,header,'repair_flags')
            rhs = hit['update'].split('|=',1)[1]
            return _result('middle_volatile_field_pointer',part,[(hit.start(),hit.end(),
                f'{{ {hit["t"]} *{local} = ({hit["t"]} *)((unsigned char *){symbol} + {hit["n"]}); *{local} |={rhs} }}')])
    return []


def zero_chain(data, offsets):
    part, _, _, _ = data
    def access(key,typ):
        return (rf'\*\s*\(\s*(?P<{key}type>{typ})\s*\*\s*\)\s*'
                rf'\(\s*(?P<{key}base>{IDENT})\s*\+\s*(?P<{key}>{NUMBER})\s*\)')
    pattern = re.compile(rf'{access("a",S16)}\s*=\s*{access("b",WORD)}\s*=\s*{access("c",S16)}\s*=\s*0\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        base = hit['abase']
        if (base!=hit['bbase'] or base!=hit['cbase'] or not _statement(part,hit.start())
                or not re.fullmatch(BYTE,_pointer_type(part,base) or '')
                or tuple(integer(hit[k]) for k in ('c','b','a')) not in offsets):
            continue
        return _result('ido_unsigned_halfword_zero_chain',part,[
            (*hit.span(key),'unsigned short') for key in ('atype','ctype')
        ])
    return []


def stack_mask(data, masks):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<statement>{IDENT}\s*\(\s*)\(\s*(?P<array>{IDENT})\s*\[\s*(?P<i>{NUMBER})\s*\]'
                         rf'\s*&\s*(?P<mask>{NUMBER})\s*\)\s*\)\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        value = integer(hit['mask'])
        decl = re.search(rf'\b{UNSIGNED}\s+{hit["array"]}\s*\[\s*({NUMBER})\s*\]\s*;',part.clean[part.opening+1:hit.start()])
        if (value not in masks or not _statement(part,hit.start()) or not decl
                or integer(hit['i'])>=integer(decl[1])
                or not _in_scope(part,part.opening+1+decl.start(),hit.start())):
            continue
        local = fresh(part.source,header,'repair_masked_word')
        return _result('stack_load_then_compound_mask',part,[(hit.start(),hit.end(),
            f'{{ unsigned int {local} = {hit["array"]}[{hit["i"]}]; {local} &= {hit["mask"]}; {hit["statement"]}{local}); }}')])
    return []


def float_loads(data, _witness):
    part, _, _, header = data
    item = rf'(?P<dst>{FIELD})\s*=\s*(?P<src>{FIELD})\s*\+\s*(?P<c>[-+]?\d+\.\d+[fF])\s*;'
    pattern = re.compile(item)
    hits = list(pattern.finditer(part.clean,part.opening+1,part.end-1))
    out = []
    for a,b in zip(hits,hits[1:]):
        fields = [re.split(r'\s*->\s*',m[k]) for m in (a,b) for k in ('dst','src')]
        if (part.clean[a.end():b.start()].strip() or not _statement(part,a.start())
                or len({p for p,_ in fields})!=1 or fields[0][1]==fields[3][1]
                or fields[0][1]==fields[2][1] or fields[1]==fields[3]
                or not _fields(data,fields[0][0],[(f,F32) for _,f in fields])):
            continue
        x,y = [fresh(part.source,header,f'repair_loaded_{i}') for i in (1,2)]
        out.extend(_result('paired_float_loads_before_adds',part,[(a.start(),b.end(),
            f'{{ float {x} = {a["src"]}; float {y} = {b["src"]}; '
            f'{a["dst"]} = {x} + {a["c"]}; {b["dst"]} = {y} + {b["c"]}; }}')]))
        if len(out)==2:
            break
    return out


def store_scopes(data, _witness):
    part, _, _, _ = data
    store = rf'{FIELD}\s*=\s*(?:{IDENT}|{NUMBER})\s*;'
    math = rf'{IDENT}\s*(?:\+=|-=)\s*(?:{IDENT}|{NUMBER})\s*;'
    shape = re.compile(rf'(?P<first>{store})\s*(?:{math}\s*){{1,3}}(?P<last>{store}\s*{store})')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        if not _statement(part,hit.start()) or re.search(r'\bdo\s*\{\s*$',part.clean[:hit.start()]):
            continue
        fields = re.findall(rf'\b({IDENT})->({IDENT})',hit[0])
        if len(set(fields))!=3 or len({p for p,_ in fields})!=1:
            continue
        middle = part.clean[hit.end('first'):hit.start('last')]
        names = re.findall(rf'\b({IDENT})\s*[-+]=',middle)
        if not all(_local(data,v,WORD,hit.start()) for v in names):
            continue
        return _result('separate_output_store_scopes',part,[
            (*hit.span(k),'do { '+part.source[slice(*hit.span(k))]+' } while (0);') for k in ('first','last')
        ])
    return []


def post_copy_narrow(data, _witness):
    part, _, _, _ = data
    shape = re.compile(rf'(?P<init>(?P<local>{IDENT})\s*=\s*\(\s*{HALF}\s*\)\s*(?P<count>{IDENT})\s*;)\s*'
                       rf'if\s*\((?P<test>[^;{{}}]+)\)\s*{{\s*(?P<copy>\*\s*{IDENT}\s*=\s*\*\s*{IDENT}\s*;)')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        local,count = hit['local'],hit['count']
        opening = part.clean.index('{',hit.end('test'),hit.end())
        end = close(part.clean,opening,'{','}')
        before = part.clean[part.opening+1:hit.start()]
        if (not end or not _statement(part,hit.start()) or not _local(data,count,WORD,hit.start())
                or not re.search(rf'\b{HALF}\s+{local}\s*;',before) or _escaped(part.body,local)
                or _refs(hit['test']+hit['copy'],local) or not _refs(part.clean[hit.end():end],local)
                or _refs(part.clean[end:part.end],local)):
            continue
        return _result('narrow_after_guarded_record_copy',part,[
            (*hit.span('init'),''),(hit.end('copy'),hit.end('copy'),' '+hit['init'])
        ])
    return []


def default_scale(part,context,shifts):
    pattern = re.compile(rf'\bdefault\s*:\s*(?P<zero>(?P<out>{IDENT})\s*=\s*0\s*;)\s*'
                         rf'(?P<skip>goto\s+(?P<done>{IDENT})\s*;)')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        common = re.search(rf'\b(?P<label>{IDENT})\s*:\s*{hit["out"]}\s*=\s*(?P<idx>{IDENT})\s*<<\s*(?P<shift>{NUMBER})\s*;'
                           rf'\s*{hit["done"]}\s*:',part.clean[hit.end():part.end])
        if not common or integer(common['shift']) not in shifts or common['idx']==hit['out']:
            continue
        idx = common['idx']
        if (block_path(part,hit.end()+common.start())!=[part.opening] or _escaped(part.body,idx)
                or not re.search(rf'\b{UNSIGNED}\s+(?:{IDENT}\s*,\s*)*{idx}\s*(?:,|;)',part.body[:hit.start()-part.opening-1])
                or _refs(part.clean[hit.end()+common.end():part.end],idx)
                or re.search(rf'^\s*#\s*define\s+{idx}\b',context,re.M)):
            continue
        return _result('default_index_through_shared_scale',part,[
            (*hit.span('zero'),f'{idx} = 0;'),(*hit.span('skip'),f'goto {common["label"]};')
        ])
    return []


def packed_word(data, offsets):
    part, _, _, header = data
    shape = re.compile(rf'\*\s*\(\s*{UNSIGNED}\s*\*\s*\)\s*\(\s*(?P<d>{IDENT})\s*\+\s*(?P<do>{NUMBER})\s*\)'
                       rf'\s*=\s*\*\s*\(\s*(?:const\s+)?{UNSIGNED}\s*\*\s*\)'
                       rf'\s*\(\s*(?P<s>{IDENT})\s*\+\s*(?P<so>{NUMBER})\s*\)\s*;')
    out = []
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        dest,src = hit['d'],hit['s']
        d,s = integer(hit['do']),integer(hit['so'])
        if (s,d) not in offsets or not _statement(part,hit.start()) or dest==src:
            continue
        local = re.search(rf'\b{BYTE}\s+{dest}\s*\[\s*({NUMBER})\s*\]\s*;',part.clean[part.opening+1:hit.start()])
        external = re.search(rf'\bextern\s+const\s+{BYTE}\s+{src}\s*\[\s*({NUMBER})\s*\]\s*;',
                             header+'\n'+part.clean[:part.opening])
        if (not local or not external or d+4>integer(local[1]) or s+4>integer(external[1])
                or not _in_scope(part,part.opening+1+local.start(),hit.start())
                or len(re.findall(rf'\b{BYTE}\s+\**\s*{dest}\b',part.body))!=1
                or re.search(rf'\b{BYTE}\s+\**\s*{src}\b',part.body)):
            continue
        tag = fresh(part.source,header,'repair_packed_word')
        out.extend(_result('isolated_unaligned_word_copy',part,[(hit.start(),hit.end(),
            f'{{ struct {tag} {{ unsigned int word; }} __attribute__((packed)); '
            f'*(struct {tag} *)(void *)({dest}+{hit["do"]}) = '
            f'*(const struct {tag} *)(const void *)({src}+{hit["so"]}); }}')]))
        if len(out)==2:
            break
    return out


def inline_invariants(source,name,header,orders):
    visible = _visible(source,name,header)
    if not visible:
        return []
    part,context = visible
    start = find(source,name)[0]
    helper = re.compile(rf'\bstatic\s+inline\s+void\s+(?P<h>{IDENT})\s*\((?P<args>[^;{{}}()]+)\)\s*{{')
    for hit in helper.finditer(part.clean,0,start):
        formals = hit['args'].split(',')
        if len(formals)!=4 or not all(re.fullmatch(rf'\s*(?:volatile\s+)?(?:{WORD}|{BYTE})\s*\*?\s*{IDENT}\s*',a) for a in formals):
            continue
        fn = hit['h']
        calls = list(re.finditer(rf'(?P<callee>\b{fn})\s*\((?P<args>[^;{{}}()]+)\)\s*;',part.body))
        if (len(calls)!=1 or _refs(_blank(header),fn) or
                len(re.findall(rf'\b{fn}\b',part.clean))!=2 or
                re.search(rf'^\s*#\s*define\s+{fn}\b',context,re.M)):
            continue
        call = calls[0]
        actuals = call['args'].split(',')
        if len(actuals)!=4:
            continue
        literals = [int(a.strip(),0) if re.fullmatch(r'(?:0x[0-9a-fA-F]+|0|[1-9][0-9]*)',a.strip()) else None for a in actuals]
        if literals.count(None)!=1 or len(set(literals))!=4:
            continue
        address = actuals[literals.index(None)].strip()
        if not re.fullmatch(rf'&?{IDENT}',address):
            continue
        for order in orders:
            if tuple(literals)==order or set(literals)!=set(order):
                continue
            slots = [literals.index(x) for x in order]
            a,b = (part.opening+1+pos for pos in call.span('args'))
            return _result('inline_loop_preheader_parameter_order',part,[
                (*hit.span('args'),', '.join(formals[i].strip() for i in slots)),
                (a,b,', '.join(actuals[i].strip() for i in slots)),
            ])
    # For a self-contained loop, the four existing initializers can become
    # the private helper's arguments. Refuse captures and other control flow.
    declaration = re.compile(rf'(?P<type>(?:volatile\s+)?(?:{WORD}|{BYTE})(?:\s*\*\s*|\s+))'
                             rf'(?P<var>{IDENT})\s*=\s*(?P<value>{NUMBER}|&?{IDENT})\s*;\s*')
    pattern = re.compile(r'\bfor\s*\(')
    for loop in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if block_path(part,loop.start())!=[part.opening]:
            continue
        prior = part.clean[part.opening+1:loop.start()]
        decls = list(declaration.finditer(prior))
        if len(decls)!=4 or declaration.sub('',prior).strip():
            continue
        atoms = [integer(m['value']) if re.fullmatch(NUMBER,m['value']) else None for m in decls]
        variables = {m['var'] for m in decls}
        if len(variables)!=4 or len(set(atoms))!=4 or atoms.count(None)!=1:
            continue
        pointer = decls[atoms.index(None)]['type']
        if 'volatile' not in pointer or '*' not in pointer or any(
            '*' in m['type'] or 'volatile' in m['type'] for m in decls if re.fullmatch(NUMBER,m['value'])
        ):
            continue
        test_end = close(part.clean,loop.end()-1)
        brace = re.match(r'\s*{',part.clean[test_end:]) if test_end else None
        end = close(part.clean,test_end+brace.end()-1,'{','}') if brace else None
        if not end or part.clean[end:part.end-1].strip() or not re.match(
            rf'\s*(?:static\s+)?void\s+{name}\s*\(',part.clean[start:part.opening]
        ):
            continue
        code = part.clean[loop.start():end]
        if (set(re.findall(r'\b[A-Za-z_]\w*\b',code))-variables-{'for'}
                or re.search(r'\b(?:goto|break|continue|return)\b',code)):
            continue
        for order in orders:
            if set(atoms)!=set(order):
                continue
            ordered = [decls[atoms.index(i)] for i in order]
            fn = fresh(source,header,'repair_ordered_loop')
            args = ', '.join(f'{m["type"].strip()} {m["var"]}' for m in ordered)
            values = ', '.join(m['value'] for m in ordered)
            return _result('inline_loop_preheader_parameter_order',part,[
                (start,start,f'static inline void {fn}({args}) {{ {code} }}\n'),
                (part.opening+1,end,f' {fn}({values}); '),
            ])
    return []


def null_epilogue(data, _witness):
    part, _, _, header = data
    pattern = re.compile(rf'\bif\s*\(\s*(?:!\s*(?P<p>{IDENT})|(?P<q>{IDENT})\s*==\s*(?:0|NULL))\s*\)'
                         rf'\s*(?:{{\s*return\s+0\s*;\s*}}|return\s+0\s*;)\s*return\s+(?P<value>[^;{{}}]+)\s*;\s*$')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        ptr = hit['p'] or hit['q']
        if (not _statement(part,hit.start()) or not re.search(
                rf'\b(?:struct\s+)?{IDENT}\s*\*\s*{ptr}\s*[,);]',part.clean[:hit.start()])
                or part.clean[part.opening+1:hit.start()].count('{')!=part.clean[part.opening+1:hit.start()].count('}')):
            continue
        # Restrict this candidate to the known word-sized result.
        name = fresh(part.source,header,'repair_result')
        success,missing,ret = [fresh(part.source,header,f'repair_{label}') for label in ('success','missing','return')]
        return _result('null_success_shared_epilogue',part,[(hit.start(),hit.end(),
            f'{{ int {name}; if ({ptr}) goto {success}; goto {missing}; '
            f'{missing}: {name} = 0; goto {ret}; '
            f'{success}: {name} = {hit["value"]}; {ret}: return {name}; }}')])
    return []


def variants(source,name,header,evidence):
    if not evidence:
        return []
    data = _context(source,name,header)
    out = []
    for method,witness in evidence:
        if method in (middle_reload,inline_invariants):
            out.extend(method(source,name,header,witness))
        elif method is default_scale:
            visible = _visible(source,name,header)
            if visible:
                out.extend(method(*visible,witness))
        elif data:
            if method is null_epilogue and not re.match(rf'\s*(?:static\s+)?{SIGNED}\s+{name}\s*\(',
                                                       data[0].clean[find(source,name)[0]:data[0].opening]):
                continue
            out.extend(method(data,witness))
    return out
