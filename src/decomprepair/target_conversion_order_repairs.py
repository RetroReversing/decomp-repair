"""Source candidates selected by the host's measured MIPS diff."""

import re

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, integer, plain_repair_view, split_args
from .operand_lifetime_repairs import _escaped, _in_scope
from .pattern_repairs import close
from .target_memory_repairs import WORD, _statement

SIGNED = r'(?:s32|int|signed(?:\s+int)?)'
UNSIGNED = r'(?:u32|unsigned(?:\s+int)?)'
F32 = r'(?:f32|float)'
F64 = r'(?:f64|double)'
S64 = r'(?:s64|(?:signed\s+)?long\s+long(?:\s+int)?)'
U64 = r'(?:u64|unsigned\s+long\s+long(?:\s+int)?)'
TYPES = rf'(?:{WORD}|{F32}|{F64}|{S64}|{U64})'


def _context(source, name, header):
    part = plain_repair_view(source, name, header)
    if not part or re.search(r'\b(?:setjmp|longjmp)\b|^\s*#\s*(?:if|elif|else|undef)\b', part.body, re.M):
        return None
    start = find(source, name)[0]
    signature = re.search(rf'\b{re.escape(name)}\s*\(([^()]*)\)\s*$', part.clean[start:part.opening])
    if not signature:
        return None
    args = signature[1]
    params = [re.fullmatch(rf'\s*({TYPES})\s+({IDENT})\s*', args[a:b]) for a,b in split_args(args)]
    declarations = {}
    for match in re.finditer(rf'\b({TYPES})\s+({IDENT}(?:\s*,\s*{IDENT})*)\s*(?=[;=])', part.body):
        pos = part.opening+1+match.start()
        if not _statement(part,pos):
            continue
        for variable in re.findall(IDENT,match[2]):
            declarations.setdefault(variable, []).append((match[1],pos))
    for p in params:
        if p:
            declarations.setdefault(p[2], []).append((p[1],part.opening))
    return part, params, declarations, header


def _local(data, var, types, pos):
    part, _, declarations, _ = data
    defs = declarations.get(var, ())
    if len(defs)!=1 or _escaped(part.body,var):
        return False
    typ, start = defs[0]
    # A second declaration of a different type (including a pointer) can
    # shadow the scalar even when it was absent from the supported list.
    if re.search(rf'(?:^|[;{{}}]|\bfor\s*\()\s*(?:{IDENT}\s+)+\*+\s*{var}\b',part.body):
        return False
    declared = re.findall(rf'(?:^|[;{{}}]|\bfor\s*\()\s*(?P<type>(?:{IDENT}\s+)+){var}\s*(?=[=;\[])',
                          part.body)
    if any(not re.fullmatch(TYPES,t.strip()) for t in declared if t.strip()!='return'):
        return False
    return bool(re.fullmatch(types,typ) and (start==part.opening or _in_scope(part,start,pos)))


def _refs(text, name):
    return re.search(rf'\b{re.escape(name)}\b',text)


def _result(family, part, changes):
    return [(family,edit(part.source,changes))]


def inequality(data, witnesses):
    part, _, _, _ = data
    xor = rf'(?P<tmp>{IDENT})\s*=\s*(?P<word>{IDENT})\s*\^\s*(?P<imm>{NUMBER})\s*;'
    call = rf'(?P<call>(?P<callee>{IDENT})\s*\([^;{{}}]*\)\s*;)'
    guard = rf'if\s*\(\s*!?\s*(?P<test>{IDENT})\s*\)\s*{{\s*{call}\s*}}'
    branch_xor = r'(?P=tmp)\s*=\s*(?P=word)\s*\^\s*(?P=imm)\s*;'
    patterns = (
        rf'(?P<remove>{xor})\s*{guard}',
        rf'if\s*\(\s*!?\s*(?P<test>{IDENT})\s*\)\s*{{\s*{call}\s*(?P<remove>{xor})\s*}}'
        rf'\s*(?P<elsearm>else\s*{{\s*{branch_xor}\s*}})',
    )
    for pattern in patterns:
        for hit in re.compile(pattern).finditer(part.clean,part.opening+1,part.end-1):
            word, tmp = hit['word'], hit['tmp']
            if ((hit['callee'],integer(hit['imm'])) not in witnesses or word==tmp or hit['test']==tmp
                    or not _statement(part,hit.start())
                    or not all(_local(data,v,WORD,hit.start()) for v in (word,tmp))
                    or _refs(hit['call'],tmp)):
                continue
            tail = re.match(rf'\s*(?:return\s+|{IDENT}\s*=\s*)(?P<expr>{tmp}\s*!=\s*0[uU]?)\s*;',
                            part.clean[hit.end():part.end])
            if not tail or _refs(part.clean[hit.end()+tail.end():part.end],tmp):
                continue
            changes = [(*hit.span('remove'),''), (hit.end()+tail.start('expr'),hit.end()+tail.end('expr'),
                                                   f'{word} != {hit["imm"]}')]
            if 'elsearm' in hit.groupdict():
                changes.append((*hit.span('elsearm'),''))
            return _result('conditional_call_inequality',part,changes)
    return []


def argument_carriers(data, positions):
    part, params, _, _ = data
    if not positions or max(positions)>=len(params) or not all(params[i] for i in positions):
        return []
    carriers = [params[i][2] for i in positions]
    conversion = re.compile(rf'(?:(?P<type>{SIGNED})\s+)?(?P<dst>{IDENT})\s*=\s*'
                            rf'\(\s*{SIGNED}\s*\)\s*(?P<src>{IDENT})\s*;')
    for first in conversion.finditer(part.clean,part.opening+1,part.end-1):
        if not _statement(part,first.start()):
            continue
        hits = [first]
        for _ in carriers[1:]:
            next_ = re.match(r'\s*',part.clean[hits[-1].end():part.end])
            hit = conversion.match(part.clean,hits[-1].end()+next_.end(),part.end)
            if not hit:
                break
            hits.append(hit)
        if len(hits)!=len(carriers):
            continue
        destinations = [hit['dst'] for hit in hits]
        tail = part.clean[hits[-1].end():part.end-1]
        if (len(set(destinations))!=len(hits) or set(destinations)&set(carriers)
                or any(not _local(data,p,SIGNED,first.start()) or _refs(tail,p) for p in carriers)
                or any(not _local(data,h['src'],F32,h.start()) for h in hits)
                or any(not h['type'] and not _local(data,h['dst'],SIGNED,h.start()) for h in hits)):
            continue
        # A single packing expression consumes the converted locals. Renaming
        # the reads in a larger tail could overwrite a live parameter or local.
        pack = re.fullmatch(r'\s*return\s+([^;{}]+);\s*',tail)
        if not pack or not re.search(r'<<|\|',pack[1]) or not re.fullmatch(r'[\w\s()<>|&^~+-]+',pack[1]):
            continue
        if not all(_refs(pack[1],v) for v in destinations) or re.search(rf'{IDENT}\s*\(',pack[1]):
            continue
        mapped = dict(zip(destinations,carriers))
        expr = re.sub(IDENT,lambda m,names=mapped:names.get(m[0],m[0]),pack[1])
        changes = [(h.start(),h.end(),f'{p} = (int){h["src"]};')
                   for h,p in zip(hits,carriers)]
        changes.append((hits[-1].end()+pack.start(1),hits[-1].end()+pack.end(1),expr))
        return _result('float_to_int_argument_carriers',part,changes)
    return []


def float_products(data, precision):
    part, _, _, _ = data
    typ = F32 if precision=='s' else F64
    term = rf'-?\s*{IDENT}'
    product = rf'{IDENT}\s*=\s*{term}\s*\*\s*{term}\s*;'
    pair = re.compile(rf'(?P<a>{product})\s*(?P<b>{product})')
    for hit in pair.finditer(part.clean,part.opening+1,part.end-1):
        if not _statement(part,hit.start()):
            continue
        (a,*left),(b,*right) = (re.findall(IDENT,hit[k]) for k in ('a','b'))
        if (a==b or {a,b}&set(left+right) or len(set(left)&set(right))!=1
                or not all(_local(data,v,typ,hit.start()) for v in (a,b,*left,*right))):
            continue
        return _result('independent_float_product_order',part,[
            (*hit.span('a'),part.source[slice(*hit.span('b'))]),
            (*hit.span('b'),part.source[slice(*hit.span('a'))]),
        ])
    return []


def modulo_selector(data, divisors):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<v>{IDENT})\s*=\s*(?P<call>(?P<callee>{IDENT})\s*\([^;{{}}]*\))\s*'
                         rf'%\s*(?P<n>{NUMBER})\s*;\s*switch\s*\(\s*(?P=v)\s*\)')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        var, callee = hit['v'],hit['callee']
        if (not _statement(part,hit.start()) or integer(hit['n']) not in divisors
                or not _local(data,var,WORD,hit.start()) or _refs(hit['call'],var)
                or _refs(part.clean[hit.end():part.end],var)):
            continue
        # Staging before % must have the same width and signedness as the
        # original callee result and literal's promoted operation.
        declarations = re.findall(rf'\b({WORD})\s+{callee}\s*\([^{{}};]*\)\s*[;{{]',
                                  part.clean[:part.opening]+header)
        signed = _local(data,var,SIGNED,hit.start())
        if not declarations or not all(re.fullmatch(SIGNED if signed else UNSIGNED,t) for t in declarations):
            continue
        if re.search(r'[lL]',hit['n']) or signed and 'u' in hit['n'].lower():
            continue
        replacement = f'{var} = {hit["call"]}; switch ({var} %= {hit["n"]})'
        return _result('in_place_modulo_switch_selector',part,[(hit.start(),hit.end(),replacement)])
    return []


def ido_store(data, callees):
    part, _, _, header = data
    member = rf'(?P<base>{IDENT})->(?P<constant>{IDENT})'
    pattern = re.compile(rf'(?P<a>{member}\s*=\s*{NUMBER}\s*;)\s*'
                         rf'(?P<b>(?P=base)->(?P<field>{IDENT})\s*=\s*(?P<arg>{IDENT})\s*;)\s*'
                         rf'(?P<call>{IDENT})\s*\(')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if (not _statement(part,hit.start()) or hit['call'] not in callees or hit['constant']==hit['field']
                or not _local(data,hit['arg'],WORD,hit.start())):
            continue
        # A plain struct pointer and two named scalar fields exclude union
        # aliasing, bit fields and overloaded accessors.
        record = re.search(rf'\bstruct\s+({IDENT})\s*\*\s*{hit["base"]}\b',
                           part.clean[:part.opening])
        if not record or _refs(part.body,record[1]):
            continue
        fields = re.search(rf'\bstruct\s+{record[1]}\s*{{([^{{}}]+)}}',header+'\n'+part.clean)
        if not fields or not all(re.search(rf'(?:^|;)\s*{WORD}\s+{v}\s*;',fields[1])
                                 for v in (hit['constant'],hit['field'])):
            continue
        return _result('ido_reload_before_constant_store',part,[
            (*hit.span('a'),part.source[slice(*hit.span('b'))]),
            (*hit.span('b'),part.source[slice(*hit.span('a'))]),
        ])
    return []


def reciprocal(data):
    part, params, _, _ = data
    float_params = {p[2] for p in params if p and re.fullmatch(F32,p[1])}
    for loop in re.finditer(r'\b(?:for|while)\s*\(',part.body):
        start = part.opening+1+loop.start()
        if not _statement(part,start) or block_path(part,start)!=[part.opening]:
            continue
        test_end = close(part.clean,part.opening+loop.end())
        brace = re.match(r'\s*{',part.clean[test_end:part.end]) if test_end else None
        end = close(part.clean,test_end+brace.end()-1,'{','}') if brace else None
        if not end:
            continue
        for var in sorted(float_params):
            expr = re.compile(rf'(?P<expr>\(\s*1\.0[fF]\s*/\s*{var}\s*\))')
            hits = list(expr.finditer(part.clean,test_end,end))
            body = expr.sub('',part.clean[test_end:end])
            if (not hits or not _local(data,var,F32,start)
                    or _refs(body,var) or _refs(part.clean[start:test_end],var)
                    or _refs(part.clean[end:part.end],var)):
                continue
            # Only enter before a loop that is guaranteed at least one trip,
            # or use a literal positive bound in the ordinary counting form.
            test = part.clean[start:test_end]
            if not re.fullmatch(rf'for\s*\(\s*({IDENT})\s*=\s*0\s*;\s*\1\s*<\s*[1-9][0-9]*\s*;'
                                rf'\s*(?:\1\+\+|\+\+\1)\s*\)',test):
                continue
            return _result('reciprocal_in_float_parameter',part,[
                (start,start,f'{var} = 1.0f / {var}; '),*((h.start(),h.end(),var) for h in hits),
            ])
    return []


def early_index(data, counts):
    part, _, _, _ = data
    pattern = re.compile(rf'(?P<dst>{IDENT})\s*=\s*\(\s*(?P<type>{F32})\s*\)\s*'
                         rf'(?P<value>{IDENT}|\([^;{{}}]+\))\s*;\s*'
                         rf'(?P<index>{IDENT})\s*=\s*(?P<word>{IDENT})\s*>>\s*(?P<n>{NUMBER})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        dst,index,word = (hit[k] for k in ('dst','index','word'))
        value = hit['value']
        if (integer(hit['n']) not in counts or not _statement(part,hit.start()) or len({dst,index,word})!=3
                or _refs(value,index) or not _local(data,dst,F32,hit.start())
                or not _local(data,index,WORD,hit.start()) or not _local(data,word,UNSIGNED,hit.start())
                or not re.fullmatch(rf'{IDENT}|\(\s*{IDENT}\s*&\s*{NUMBER}\s*\)',value)
                or not _local(data,re.search(IDENT,value)[0],UNSIGNED,hit.start())
                or not re.search(rf'\[\s*{index}\s*\]',part.clean[hit.end():part.end])):
            continue
        return _result('table_index_before_float_conversion',part,[
            (hit.start(),hit.end(),f'{index} = {word} >> {hit["n"]}; {dst} = ({hit["type"]}){value};')
        ])
    return []


def table_offset(data, symbols):
    part, _, _, header = data
    for symbol in sorted(symbols):
        declarations = set(re.findall(rf'\b(?:s8|signed\s+char)\s+{symbol}\s*\[\s*(?:{NUMBER})?\s*\]'
                                      rf'\s*\[\s*({NUMBER})\s*\]',header+'\n'+part.clean[:part.opening]))
        if len(declarations)!=1:
            continue
        stride = integer(next(iter(declarations)))
        if not 1<stride<=65535 or re.search(rf'\b{symbol}\b\s*(?=[;=])',part.body):
            continue
        pattern = re.compile(rf'\b{symbol}\s*\[\s*(?P<row>{IDENT})\s*\]\s*\[\s*(?P<col>{IDENT}|{NUMBER})\s*\]')
        hits = list(pattern.finditer(part.clean,part.opening+1,part.end-1))
        if len(hits)!=2 or not block_path(part,hits[0].start()) or block_path(
                part,hits[0].start())!=block_path(part,hits[1].start()):
            continue
        out = []
        for hit in hits:
            if (not _local(data,hit['row'],WORD,hit.start()) or
                    (re.fullmatch(IDENT,hit['col']) and not _local(data,hit['col'],WORD,hit.start()))
                    or re.match(r'\s*(?:[+*/%&|^<>-]?=(?!=)|\+\+|--)',part.clean[hit.end():])
                    or re.search(r'(?:&|\+\+|--|sizeof)\s*\(?\s*$',part.clean[:hit.start()])):
                return []
            address = f'((signed char *)&{symbol})[(long){hit["row"]} * {stride} + (long){hit["col"]}]'
            out.extend(_result('one_strided_table_byte_offset',part,[(hit.start(),hit.end(),address)]))
        return out
    return []


def signed_bound(data):
    part, _, _, _ = data
    pattern = re.compile(rf'(?P<expr>\(?\s*(?P<a>{IDENT})\s*-\s*(?P<b>{IDENT})\s*\)?)'
                         rf'\s*(?:<=|>=|<|>)\s*(?P<bound>{IDENT})\b')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        expr = hit['expr']
        if (expr.count('(')!=expr.count(')') or not _local(data,hit['bound'],S64,hit.start())
                or not all(_local(data,hit[k],rf'(?:{S64}|{U64})',hit.start()) for k in ('a','b'))
                or not any(_local(data,hit[k],U64,hit.start()) for k in ('a','b'))):
            continue
        prefix = part.clean[part.opening+1:hit.start()]
        if not re.search(r'(?:\bif\s*\(|\breturn|(?<![=!<>])=)\s*$',prefix):
            continue
        return _result('signed_high_word_bound',part,[(*hit.span('expr'),f'(long long)({expr})')])
    return []


def named_bias(data, symbols):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<dst>{IDENT})\s*=\s*\(\s*{F64}\s*\)\s*(?P<word>{IDENT})\s*;')
    for symbol in sorted(symbols):
        if not re.search(rf'\bextern\s+const\s+{F64}\s+{symbol}\s*;',header+'\n'+part.clean[:part.opening]):
            continue
        if _refs(part.body,symbol):
            continue
        changes = []
        for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
            dst, word = hit['dst'],hit['word']
            if (_statement(part,hit.start()) and _local(data,dst,F64,hit.start())
                    and _local(data,word,UNSIGNED,hit.start())):
                temp = fresh(part.source,header,'repair_signed_word')
                replacement = (f'{{ int {temp} = (int){word}; {dst} = (double){temp}; '
                               f'if ({temp} < 0) {{ {dst} += {symbol}; }} }}')
                changes.append((hit.start(),hit.end(),replacement))
        if changes:
            return _result('named_unsigned_double_bias',part,changes[:4])
    return []


def variants(source, name, header, evidence):
    if not evidence:
        return []
    data = _context(source,name,header)
    if not data:
        return []
    out = []
    for repair, args in evidence:
        out.extend(repair(data,*args))
    return out
