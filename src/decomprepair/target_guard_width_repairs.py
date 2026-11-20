"""Source candidates for measured guard, load, and integer-width differences."""

import re

from .compiler_phase_repairs import fresh
from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, integer
from .operand_lifetime_repairs import _escaped, _in_scope
from .pattern_repairs import close
from .target_conversion_order_repairs import F32, UNSIGNED, _context, _local, _refs, _result
from .target_edge_repairs import HALF
from .target_memory_repairs import WORD, _statement

BYTE = r'(?:u8|unsigned\s+char)'
SBYTE = r'(?:s8|signed\s+char)'
SCALAR = rf'(?:{WORD}|{HALF}|{BYTE}|{SBYTE}|{F32}|short|s16)'
POINTER = rf'(?:const\s+)?(?:struct\s+)?{IDENT}'
NONNULL = rf'(?P<ptr>{IDENT})(?:\s*!=\s*(?:NULL|0))?'


def _pointer_type(part, name, start=0):
    pattern = rf'\b({POINTER})\s*\*\s*{name}\s*(?=[;,)])'
    found = re.findall(pattern,part.clean[start:part.end])
    return found[0] if len(found)==1 else None


def _fields(data, ptr, fields):
    part, _, _, header = data
    typ = _pointer_type(part,ptr)
    record = re.fullmatch(rf'(?:const\s+)?struct\s+({IDENT})',typ or '')
    if not record:
        return False
    layouts = re.findall(rf'\bstruct\s+{record[1]}\s*{{([^{{}}]+)}}',header+'\n'+part.clean[:part.opening])
    return len(layouts)==1 and all(re.search(
        rf'(?:^|;)\s*{kind}\s+(?:{IDENT}\s*,\s*)*{name}\s*(?=,|;)',layouts[0]
    ) for name,kind in fields)


def nonnull_pointer(data, _witness, *, function_start=0):
    part, _, _, header = data
    for guard in re.finditer(rf'\bif\s*\(\s*{NONNULL}\s*\)\s*{{',part.body):
        ptr = guard['ptr']
        opening = part.opening+guard.end()
        end = close(part.clean,opening,'{','}')
        typ = _pointer_type(part,ptr,function_start)
        if (not typ or not end or _escaped(part.body,ptr)
                or re.search(rf'\b(?:static|extern)\s+{POINTER}\s*\*\s*{ptr}\b',part.body)):
            continue
        body = part.clean[opening+1:end-1]
        hits = list(re.finditer(rf'\b{ptr}\b(?=\s*->)',body))
        # Restrict the snapshot to the tested local and recognized field uses.
        # Calls may use its value but cannot change the unescaped binding.
        if len(hits)<2 or len(re.findall(rf'\b{ptr}\b',body))!=len(hits):
            continue
        declared = re.search(rf'\b{re.escape(typ)}\s*\*\s*{ptr}\s*(?=[;,)])',part.clean[:opening],re.M)
        if not declared or declared.start()<function_start or (declared.start()>part.opening and not _in_scope(part,declared.start(),opening)):
            continue
        if re.search(r'\bcase\b|(?:^|[;{}])\s*\w+\s*:',body):
            continue
        name = fresh(part.source,header,'repair_body_pointer')
        return _result('nonnull_guard_pointer_local',part,[
            (opening+1,opening+1,f' {typ} *{name} = {ptr}; '),
            *((opening+1+h.start(),opening+1+h.end(),name) for h in hits),
        ])
    return []


def fallthrough_float(data, _witness):
    part, _, _, header = data
    member = rf'{IDENT}\s*->\s*{IDENT}'
    compare = rf'(?:{member}\s*(?:<=|>=|<|>)\s*{IDENT}|{IDENT}\s*(?:<=|>=|<|>)\s*{member})'
    pattern = re.compile(rf'\bif\s*\(\s*(?P<one>{compare})\s*(?P<join>&&|\|\|)\s*'
                         rf'(?P<two>{compare})\s*\)\s*{{')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        end = close(part.clean,hit.end()-1,'{','}')
        first, second = (re.search(member,hit[k]) for k in ('one','two'))
        ptr,field_name = re.split(r'\s*->\s*',first[0])
        if (not end or not _statement(part,hit.start()) or re.match(r'\s*else\b',part.clean[end:])
                or re.split(r'\s*->\s*',second[0])!=[ptr,field_name]
                or not all(_local(data,re.search(IDENT,hit[key].replace(m[0],''))[0],F32,hit.start())
                           for key,m in (('one',first),('two',second)))
                or not _fields(data,ptr,[(field_name,F32)])):
            continue
        name = fresh(part.source,header,'repair_compare_field')
        field = first[0]
        left,right = (hit[k].replace(m[0],name) for k,m in (('one',first),('two',second)))
        prefix = (f'{{ float {name} = {field}; if ({left} {hit["join"]} ({name} = {field}, {right})) {{')
        direct = _result('fallthrough_float_field_reload',part,[(hit.start(),hit.end(),prefix),(end,end,' }')])
        label = fresh(part.source,header,'repair_compare_join')
        predicate = fresh(part.source,header,'repair_compare_result')
        conjunction = hit['join']=='&&'
        short = f'!({left})' if conjunction else left
        explicit = (f'{{ float {name} = {field}; int {predicate} = {0 if conjunction else 1}; '
                    f'if ({short}) goto {label}; {name} = {field}; {predicate} = {right}; '
                    f'{label}: if ({predicate}) {{')
        return direct + _result('fallthrough_float_field_reload',part,[
            (hit.start(),hit.end(),explicit),(end,end,' }')
        ])
    return []


def mask_literal(data, witnesses):
    part, _, _, header = data
    for symbol,value in sorted(witnesses):
        # Match a whole bitwise operation on a known integer input.
        # Subscripting, dereferencing, and pointer arithmetic do not qualify.
        pattern = re.compile(rf'(?P<word>{IDENT})\s*(?:\|(?!\|)|&(?!&)|\^)\s*'
                             rf'(?P<cast>\(\s*{UNSIGNED}\s*\)\s*&\s*{symbol})\b(?=\s*[);])')
        if not re.search(rf'\bextern\s+[^;{{}}]+\b{symbol}\s*;',header+'\n'+part.clean[:part.opening]):
            continue
        if _refs(part.body,symbol) and re.search(rf'\b{SCALAR}\s+\**\s*{symbol}\s*(?=[;=,])',part.body):
            continue
        for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
            if _local(data,hit['word'],WORD,hit.start()):
                return _result('resolved_high_bit_mask_literal',part,[(*hit.span('cast'),f'0x{value:08X}U')])
    return []


def normalized_mask_or(data, masks):
    part, _, _, _ = data
    pattern = re.compile(rf'\bif\s*\(\s*\(\s*(?P<a>{IDENT})\s*&\s*(?P<x>{NUMBER})\s*\)'
                         rf'\s*\|(?!\|)\s*\(\s*(?P<b>{IDENT})\s*&\s*(?P<y>{NUMBER})\s*\)\s*\)')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        if ((integer(hit['x']),integer(hit['y'])) not in masks
                or not all(_local(data,hit[k],WORD,hit.start()) for k in ('a','b'))):
            continue
        value = f'if ((({hit["a"]} & {hit["x"]}) != 0) | (({hit["b"]} & {hit["y"]}) != 0))'
        return _result('normalize_masked_operands_before_or',part,[(hit.start(),hit.end(),value)])
    return []


def unbiased_cursor(data, _witness):
    part, _, _, header = data
    for loop in re.finditer(r'\bdo\s*{',part.body):
        start,opening = part.opening+1+loop.start(),part.opening+loop.end()
        end = close(part.clean,opening,'{','}')
        tail = re.match(r'\s*while\s*\(',part.clean[end:part.end]) if end else None
        if not tail or not _statement(part,start):
            continue
        test_end = close(part.clean,end+tail.end()-1)
        finish = re.match(r'\s*;',part.clean[test_end:]) if test_end else None
        body = part.clean[opening+1:end-1]
        if not finish or re.search(r'\b(?:break|continue|goto|switch|for|while|do)\b|(?:^|[;{}])\s*\w+\s*:',body):
            continue
        if not re.search(rf'\b{IDENT}\s*(?:\+=\s*{NUMBER}|\+\+)\s*;\s*$',body):
            continue
        if len(re.findall(rf'\*\s*\([^;]*?{IDENT}\b[^;]*?\)\s*=|{IDENT}->\w+\s*=',body))<2:
            continue
        name = fresh(part.source,header,'repair_record_loop')
        test = part.source[end+tail.end():test_end-1]
        return _result('unbiased_record_cursor_backedge',part,[
            (start,opening,f'{{ {name}: '),
            (end,test_end+finish.end(),f' if ({test}) goto {name}; }}'),
        ])
    return []


def embedded_flag(data, _witness):
    part, _, _, _ = data
    shape = re.compile(rf'(?P<init>(?P<flag>{IDENT})\s*=\s*(?P<rhs>[^;{{}}]+&\s*1[uU]?)\s*;)\s*'
                       rf'if\s*\(\s*(?P<test>(?P=flag))(?:\s*!=\s*0)?\s*\)')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        flag = hit['flag']
        declaration = re.search(rf'\b{BYTE}\s+{flag}\s*;',part.clean[part.opening+1:hit.start()])
        position = part.opening+1+declaration.start() if declaration else -1
        if (not declaration or not _statement(part,hit.start()) or not _in_scope(part,position,hit.start())
                or _escaped(part.body,flag) or len(re.findall(rf'\b{SCALAR}\s+\**\s*{flag}\b',part.body))!=1):
            continue
        return _result('byte_flag_assignment_in_test',part,[
            (*hit.span('init'),''),(*hit.span('test'),f'({flag} = {hit["rhs"]})')
        ])
    return []


def null_immediate(data, values):
    part, _, _, header = data
    for guard in re.finditer(rf'\bif\s*\(\s*{NONNULL}\s*\)\s*{{',part.body):
        ptr, opening = guard['ptr'],part.opening+guard.end()
        start = part.opening+1+guard.start()
        end = close(part.clean,opening,'{','}')
        if not end or not _statement(part,start) or re.match(r'\s*else\b',part.clean[end:]):
            continue
        body = part.clean[opening+1:end-1]
        first = re.match(rf'\s*{ptr}->({IDENT})\s*=\s*[^;{{}}]+;',body)
        if not first:
            continue
        fields = list(re.finditer(rf'\b{ptr}->(?P<field>{IDENT})\s*=\s*(?P<value>{NUMBER})\s*;',body[first.end():]))
        for value in sorted(values):
            uses = [f for f in fields if integer(f['value'])==value]
            if len({f['field'] for f in uses})<2 or not _fields(
                data,ptr,[(first[1],rf'(?:{HALF}|s16|short)'),*((f['field'],BYTE) for f in uses)]
            ):
                continue
            name = fresh(part.source,header,'repair_store_byte')
            at = opening+1+first.end()
            return _result('null_guard_repeated_store_immediate',part,[
                (start,opening,f'{{ unsigned char {name}; if (({name} = {value}, {ptr}) != 0) '),
                *((at+f.start('value'),at+f.end('value'),name) for f in uses),(end,end,' }'),
            ])
    return []


def split_seed(data, values):
    part, _, _, header = data
    pattern = re.compile(rf'(?P<i>{IDENT})\s*=\s*(?P<n>{NUMBER})\s*;\s*'
                         rf'if\s*\(\s*(?P=i)\s*<\s*(?P<bound>{IDENT})\s*\)\s*{{')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        value, index, bound = integer(hit['n']),hit['i'],hit['bound']
        end = close(part.clean,hit.end()-1,'{','}')
        if (bound==index or value not in values or not 0<value<256 or not end or not _statement(part,hit.start())
                or not _local(data,index,WORD,hit.start()) or not _local(data,bound,WORD,hit.start())
                or re.match(r'\s*else\b',part.clean[end:])):
            continue
        body = part.clean[hit.end():end-1]
        if not re.search(r'\b(?:do|while|for)\b',body) or not re.search(rf'\b{index}\s*(?:\+\+|\+=\s*1)',body):
            continue
        seed = fresh(part.source,header,'repair_entry_seed')
        more = fresh(part.source,header,'repair_enter_loop')
        typ = data[2][index][0][0]
        repl = (f'{{ unsigned char {seed} = {hit["n"]}; int {more} = ({typ}){seed} < {bound}; '
                f'{index} = {hit["n"]}; if ({more}) {{')
        return _result('entry_seed_and_induction_split',part,[(hit.start(),hit.end(),repl),(end,end,' }')])
    return []


def ordinary_halfword(data, _witness):
    part, _, _, _ = data
    pattern = re.compile(rf'\*\s*\(\s*(?P<qual>volatile\s+){HALF}\s*\*\s*\)\s*&\s*(?P<local>{IDENT})\b')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        local = hit['local']
        decl = re.search(rf'\b{HALF}\s+{local}\s*(?:=[^;{{}}]+)?;',part.clean[part.opening+1:hit.start()])
        remaining = part.body[:hit.start()-part.opening-1]+part.body[hit.end()-part.opening-1:]
        if (not decl or not _in_scope(part,part.opening+1+decl.start(),hit.start())
                or _escaped(remaining,local)
                or len(re.findall(rf'\b{SCALAR}\s+\**\s*{local}\b',part.body))!=1):
            continue
        return _result('ordinary_local_halfword_read',part,[(*hit.span('qual'),'')])
    return []


def signed_adjust(data, _witness):
    part, _, _, header = data
    shape = re.compile(rf'if\s*\(\s*\(\s*{SBYTE}\s*\)\s*(?P<raw>{IDENT})\s*<\s*0\s*\)\s*{{\s*'
                       rf'(?P<block>(?P<tmp>{IDENT})\s*=\s*(?P=raw)\s*;\s*'
                       rf'(?P=tmp)\s*(?:--|-=\s*1)\s*;\s*(?P=tmp)\s*=\s*-\s*(?P=tmp)\s*;\s*'
                       rf'{IDENT}(?:->\w+|\[[^;{{}}]+\])\s*=\s*\(\s*{BYTE}\s*\)\s*(?P=tmp)\s*;)\s*}}')
    for hit in shape.finditer(part.clean,part.opening+1,part.end-1):
        tmp = hit['tmp']
        if (not _local(data,tmp,UNSIGNED,hit.start()) or not _local(data,hit['raw'],WORD,hit.start())
                or _refs(part.clean[hit.end():part.end],tmp)
                or len(re.findall(rf'\b{tmp}\b',hit['block']))!=5):
            continue
        name = fresh(part.source,header,'repair_adjusted_byte')
        body = re.sub(rf'\b{tmp}\b',name,hit['block'])
        return _result('signed_byte_adjustment_local',part,[(*hit.span('block'),f'signed char {body}')])
    return []


def variants(source,name,header,evidence):
    if not evidence:
        return []
    data = _context(source,name,header)
    # Only the ordinary-memory rule inspects a volatile cast. Strip that
    # qualifier from the lexical proof view, keeping source spans intact.
    ordinary = data
    if any(fn is ordinary_halfword for fn,_ in evidence):
        masked = re.sub(rf'(?<=\()\s*volatile(?=\s+{HALF}\s*\*)',
                        lambda hit:' '*len(hit[0]),source)
        checked = _context(masked,name,header)
        if checked:
            actual = type(checked[0])(source, _blank(source), checked[0].opening, checked[0].end)
            ordinary = (actual,*checked[1:])
    out = []
    for repair,witness in evidence:
        current = ordinary if repair is ordinary_halfword else data
        if current:
            if repair is nonnull_pointer:
                out.extend(repair(current,witness,function_start=find(source,name)[0]))
            else:
                out.extend(repair(current,witness))
    return out
