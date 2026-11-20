"""Arithmetic lifetime and conversion patterns selected by measured machine code."""

import re
from decimal import Decimal

from .call_lifetime_repairs import block_path
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, plain_repair_view, refs

SQUARES = 'staged_squared_terms'
DOUBLE = 'double_unsigned_conversion'
DIVISIONS = 'separated_unsigned_divisions'
MINMAX = 'in_place_minmax'
UNSIGNED = r'(?:u32|unsigned(?:\s+int)?)'
SIGNED = r'(?:s32|int|signed(?:\s+int)?)'


def squared_terms(source, name, header):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    declarations = re.compile(rf'\b(?P<type>float|double|f32|f64)\s+(?P<name>{IDENT})\s*(?=[;=])')
    types = {m['name']:m['type'] for m in declarations.finditer(part.clean, part.opening+1, part.end-1)
             if block_path(part,m.start()) == [part.opening]}
    product = rf'({IDENT})\s*\*\s*\1'
    # Match the flat sum only. Do not reassociate parenthesized values or
    # evaluate a square at a different argument's evaluation point.
    stmt = re.compile(rf'(?:return\s+|{IDENT}\s*\(\s*)(?P<terms>{IDENT}\s*\*\s*{IDENT}'
                      rf'(?:\s*\+\s*{IDENT}\s*\*\s*{IDENT}){{1,3}})\s*\)?\s*;')
    for hit in stmt.finditer(part.clean, part.opening+1,part.end-1):
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        start, stop = hit.span('terms')
        terms = list(re.finditer(product, part.clean[start:stop]))
        if len(terms) != 1+hit['terms'].count('+'):
            continue
        names = [term[1] for term in terms]
        if len(set(names)) != len(names) or any(n not in types for n in names):
            continue
        if len({types[n] for n in names}) != 1:
            continue
        result = []
        # Staging through the same typed local only applies when its old
        # value cannot be read later or through an escaped address.
        for count in range(1,len(terms)):
            selected = terms[:count]
            taken = {term[1] for term in selected}
            if any(re.search(rf'\b{n}\b',part.clean[hit.end():part.end]) or re.search(
                    rf'(?<!&)&(?!&)\s*\(*\s*{n}\b',part.body) for n in taken):
                break
            if block_path(part, hit.start()) != [part.opening]:
                continue
            prefix = ' '.join(f'{term[1]} = {term[1]} * {term[1]};' for term in selected)
            changes = [(start+t.start(),start+t.end(),t[1]) for t in selected]
            result.append((SQUARES,edit(source,[(hit.start(),hit.start(),prefix+' '),*changes])))
        if result:
            return result
    return []


_DECIMAL = r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?'


def double_unsigned(source, name, header):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    lvalue = rf'{IDENT}(?:\s*->\s*{IDENT})?'
    condition = (rf'if\s*\(\s*(?P<value>{IDENT})\s*(?P<compare>>=|<)\s*'
                 rf'(?P<bound>{_DECIMAL})\s*\)\s*')
    arm = rf'{{\s*(?P<dest>{lvalue})\s*=(?!=)\s*(?P<rhs>[^;{{}}]+);\s*}}'
    pair = re.compile(condition+arm+r'\s*else\s*'+arm.replace('P<dest>', 'P<other>').replace('P<rhs>','P<rhs2>'))
    result = []
    for hit in pair.finditer(part.clean, part.opening+1, part.end-1):
        bound = hit['bound']
        value = hit['value']
        if len(bound) > 32 or Decimal(bound) != 2147483648:
            continue
        if not re.search(rf'\b(?:f64|double)\s+{value}\b',part.clean[:hit.start()]):
            continue
        if re.sub(r'\s+', '', hit['dest']) != re.sub(r'\s+', '', hit['other']):
            continue
        high, low = (hit['rhs'],hit['rhs2']) if hit['compare'] == '>=' else (hit['rhs2'],hit['rhs'])
        if not re.fullmatch(rf'\s*\(\s*{SIGNED}\s*\)\s*{value}\s*',low):
            continue
        high_pattern = (rf'\s*\(*\s*\(\s*{SIGNED}\s*\)\s*\(\s*{value}\s*-\s*'
                        rf'({_DECIMAL})\s*\)\s*\)?\s*\|\s*0[xX]80000000[uU]?\s*\)*\s*')
        high_value = re.fullmatch(high_pattern,high)
        if not high_value or len(high_value[1]) > 32 or Decimal(high_value[1]) != 2147483648:
            continue
        result.append((DOUBLE,edit(source,[(hit.start(),hit.end(),f"{hit['dest']} = (u32){value};")])))
        if len(result) == 2:
            break
    return result


def separated_divisions(source, name, header, divisors):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    quotients = re.compile(rf'(?P<dest>{IDENT})\s*=(?!=)\s*'
                           rf'(?P<expr>(?P<value>{IDENT})(?:\s*\*\s*(?:{IDENT}|{NUMBER}))?)'
                           rf'\s*/\s*(?P<divisor>{NUMBER})\s*;')
    typed = {d['name'] for d in locals_for(part) if re.fullmatch(UNSIGNED,d['type'])}
    signature = part.clean[max(part.clean.rfind(ch,0,part.opening) for ch in ';{}')+1:part.opening]
    typed.update(re.findall(rf'{UNSIGNED}\s+({IDENT})\s*(?=[,)])', signature))
    result = []
    for hit in quotients.finditer(part.clean,part.opening+1,part.end-1):
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        if hit['value'] not in typed:
            continue
        divisor = integer(hit['divisor'])
        for first,second in divisors:
            if first*second != divisor:
                continue
            temp = fresh(source,header,'repair_quotient')
            replacement = f"{{ unsigned {temp} = {hit['expr']} / {first}U; {hit['dest']} = {temp} / {second}U; }}"
            result.append((DIVISIONS,edit(source,[(hit.start(),hit.end(),replacement)])))
            if len(result) == 4:
                return result
    return result


def in_place_minmax(source, name, header):
    part = plain_repair_view(source, name, header)
    if not part:
        return []
    locals_ = {decl['name']:decl for decl in locals_for(part)}
    pattern = re.compile(
        rf'(?P<a>{IDENT})\s*=(?!=)\s*(?P<x>{IDENT})\s*-\s*(?P<u>{IDENT})\s*;\s*'
        rf'(?P<b>{IDENT})\s*=(?!=)\s*(?P<y>{IDENT})\s*-\s*(?P<v>{IDENT})\s*;\s*'
        rf'(?P<dest>{IDENT})\s*=(?!=)\s*\(?(?P=a)\s*(?P<op>[<>])\s*(?P=b)\s*\)?\s*'
        rf'\?\s*(?P<yes>{IDENT})\s*:\s*(?P<no>{IDENT})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end-1):
        prefix = part.clean[part.opening+1:hit.start()].rstrip()
        if prefix and prefix[-1] not in ';{}':
            continue
        a,b,x,y,u,v = (hit[key] for key in ('a','b','x','y','u','v'))
        if len({a,b,x,y}) != 4 or {hit['yes'],hit['no']} != {a,b} or {a,b,x,y} & {u,v,hit['dest']}:
            continue
        if not all(n in locals_ and locals_[n].end() <= hit.start() and
                   block_path(part, locals_[n].start()) == block_path(part,hit.start()) for n in (a,b,x,y)):
            continue
        if len({locals_[n]['type'] for n in (a,b,x,y)}) != 1:
            continue
        if any(any(ref.start() >= hit.end() for ref in refs(part,locals_[n])) for n in (a,b,x,y)):
            continue
        dest, op = hit['dest'], hit['op']
        mapping = {a:x,b:y}
        yes,no = mapping[hit['yes']],mapping[hit['no']]
        update = f'{x} -= {u}; {y} -= {v}; '
        return [(MINMAX,edit(source,[(hit.start(),hit.end(),update+form)])) for form in
                (f'{dest} = ({x} {op} {y}) ? {yes} : {no};',
                 f'if ({x} {op} {y}) {{ {dest} = {yes}; }} else {{ {dest} = {no}; }}')]
    return []
