"""Address edits backed by a paired MIPS relocation, add, or store mismatch."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .kmc_operand_repairs import ADDU
from .target_constant_repairs import LITERAL

REG = r'\$\w+'
DATA = r'D_[0-9A-Fa-f]{8}'
REFERENCE = rf'{IDENT}(?:[+-]0x[0-9a-fA-F]+)?'
HIGH = re.compile(rf'lui\s+({REG}),\s*%hi\(({REFERENCE})\)')
LOW = re.compile(rf'addiu\s+({REG}),\s*({REG}),\s*%lo\(({REFERENCE})\)')
EXTERN = re.compile(rf'\bextern\s+(?P<type>{IDENT}(?:[ \t]+{IDENT})*)[ \t]+'
                    rf'(?P<name>{DATA})\s*(?P<array>\[\s*\])?\s*;')
STORE = re.compile(rf'sw\s+({REG}),\s*(-?(?:0x[0-9a-f]+|\d+))?\(({REG})\)')


def address(reference, symbols):
    match = re.fullmatch(rf'({IDENT})([+-]0x[0-9a-fA-F]+)?', reference)
    base = symbols.resolve(match[1])
    return base + int(match[2] or '0', 0) if base is not None else None


def relocation_pairs(changes, symbols):
    if not 2 <= len(changes) <= 6 or len(changes) % 2:
        return None
    pairs = set()
    for high, low in zip(changes[::2], changes[1::2]):
        i, hi_marker, left, right = high
        j, lo_marker, left_lo, right_lo = low
        if j != i+1 or hi_marker != 'i' or lo_marker != 'i':
            return None
        h, old_h = HIGH.fullmatch(left), HIGH.fullmatch(right)
        l, old_l = LOW.fullmatch(left_lo), LOW.fullmatch(right_lo)
        if (not all((h, old_h, l, old_l)) or not re.fullmatch(DATA,h[2])
                or (h[1], h[1], h[2]) != l.groups()
                or (old_h[1], old_h[1], old_h[2]) != old_l.groups() or h[1] != old_h[1]):
            return None
        target = symbols.by_name.get(h[2])
        old_address = address(old_h[2], symbols)
        if (target is None or target.kind not in ('data','bss') or old_address is None
                or old_address == target.address):
            return None
        pairs.add((old_address,h[2]))
    return next(iter(pairs)) if len(pairs) == 1 else None


def relocation_binding(source, header, part, rows, changes, symbols):
    if symbols is None or not (pair := relocation_pairs(changes,symbols)):
        return None
    old_address, target = pair
    # A remaining matched load/address of this object makes a blanket rename ambiguous.
    for marker, _, candidate in rows:
        refs = re.findall(rf'%(?:hi|lo)\(({REFERENCE})\)',candidate)
        if marker == ' ' and any(address(ref,symbols) == old_address for ref in refs):
            return None
    declarations = [decl for decl in EXTERN.finditer(part.clean,0,part.opening)
                    if symbols.resolve(decl['name']) == old_address
                    and re.search(rf'\b{decl["name"]}\b',part.body)]
    if len(declarations) != 1:
        return None
    decl = declarations[0]
    old = decl['name']
    old_token = rf'\b{old}\b'
    if (re.search(r'\b(?:const|volatile)\b',decl['type'])
            or re.search(old_token,_blank(header))
            or re.search(rf'\b{target}\b',part.clean+'\n'+_blank(header))
            or len(re.findall(old_token,part.clean)) != len(re.findall(old_token,part.body))+1
            or re.search(rf'\b{old}\s*(?:=(?!=)|\+\+|--|\s*\+=|\s*-=)',part.body)):
        return None
    uses = list(re.finditer(old_token,part.body))
    if not decl['array'] and any(not re.search(r'&\s*$',part.body[max(0,use.start()-12):use.start()]) for use in uses):
        return None
    return edit(source,[(decl.start('name'),decl.end('name'),target),
                        *((part.opening+1+use.start(),part.opening+1+use.end(),target) for use in uses)])


def address_add(source, part, left, right):
    a,b = ADDU.fullmatch(left),ADDU.fullmatch(right)
    if not a or not b or a[2] == a[3] or a.groups() != (b[1],b[3],b[2]):
        return []
    result = []
    # A word global supplying a raw base can commute with a side-effect-free scaled local.
    raw = re.compile(rf'\(\s*(?:u8|s8|u16|s16|u32|s32)\s*\*\s*\)\s*\(\s*'
                     rf'(?P<sum>(?P<base>{DATA})\s*\+\s*(?P<index>{IDENT})\s*\*\s*(?P<step>{LITERAL.pattern}))\s*\)')
    for hit in raw.finditer(part.clean,part.opening+1,part.end):
        if (integer(hit['step']) in (2,4,8,16,32)
                and re.search(rf'\bextern\s+(?:s32|u32|int)\s+{hit["base"]}\s*;',part.clean[:part.opening])
                and re.search(rf'\b(?:s32|u32|s16|u16|int)\s+{hit["index"]}\s*;',part.body)):
            result.append(edit(source,[(*hit.span('sum'),f'{hit["index"]} * {hit["step"]} + {hit["base"]}')]))
    # The source already forms byte offsets, so exposing the add as integer
    # arithmetic preserves the byte scaling while letting KMC change operand order.
    byte = re.compile(rf'\breturn\s+(?P<sum>(?P<base>{IDENT})\s*\+\s*'
                      rf'(?P<offset>\(\s*{IDENT}\s*<<\s*[1-5]\s*\)))\s*;')
    if re.search(rf'\bvoid\s*\*\s*{IDENT}\s*\([^;{{}}]*\)\s*$',part.clean[:part.opening]):
        for hit in byte.finditer(part.clean,part.opening+1,part.end):
            if re.search(rf'\b(?:u8|s8|char)\s*\*\s*{hit["base"]}\s*=',part.body):
                result.append(edit(source,[(*hit.span('sum'),f'(void *)({hit["offset"]} + (unsigned int){hit["base"]})')]))
    index = re.compile(rf'&\s*(?P<base>{IDENT})\s*\[\s*(?P<index>\(\s*(?:u8|s8|u16|s16)\s*\)\s*{IDENT})\s*\]')
    for hit in index.finditer(part.clean,part.opening+1,part.end):
        declarations = list(re.finditer(rf'\b({IDENT})\s*\*\s*\*\s*{hit["base"]}\s*=',part.body))
        if len(declarations) == 1:
            replacement = (f'({declarations[0][1]} **)(((unsigned int){hit["index"]} * sizeof(*{hit["base"]})) '
                           f'+ (unsigned int){hit["base"]})')
            result.append(edit(source,[(*hit.span(),replacement)]))
    return list(dict.fromkeys(result))[:3]


def reciprocal_links(source, part, changes):
    (i,_,left,right),(j,_,left_next,right_next) = changes
    a,b = STORE.fullmatch(left),STORE.fullmatch(left_next)
    if (j != i+1 or (left,left_next) != (right_next,right)
            or not a or not b or a[3] != b[3] or a[2] == b[2]
            or a[3] in ('$sp','$fp','$s8','$gp')):
        return None
    item = rf'(?P<array>{IDENT})\s*\[\s*(?P<index>{IDENT})\s*\]'
    previous = r'(?P=array)\s*\[\s*(?P=index)\s*-\s*1\s*\]'
    current = r'(?P=array)\s*\[\s*(?P=index)\s*\]'
    pattern = re.compile(rf'(?P<prev>\b{item}\s*\.\s*prev\s*=\s*&\s*{previous}\s*;)'
                         rf'(?P<gap>\s*)(?P<next>{previous}\s*\.\s*next\s*=\s*&\s*{current}\s*;)')
    sites = list(pattern.finditer(part.clean,part.opening+1,part.end))
    if len(sites) != 1:
        return None
    hit = sites[0]
    # Keep comments and line placement untouched when the pair is not plain.
    if re.search(r'/[*/]',source[slice(*hit.span())]):
        return None
    return edit(source,[(*hit.span(),source[slice(*hit.span('next'))]+hit['gap']+source[slice(*hit.span('prev'))])])


def variants(source, name, header, rows, symbols=None):
    changes = [(i,marker,left,right) for i,(marker,left,right) in enumerate(rows) if marker != ' ']
    if (not 1 <= len(changes) <= 6 or not (part := view(source,name))
            or re.search(r'\b(?:volatile|asm|__asm__)\b',part.body)):
        return []
    if len(changes) == 1:
        _,_,left,right = changes[0]
        return [('measured_address_add',candidate) for candidate in address_add(source,part,left,right)]
    if candidate := relocation_binding(source,header,part,rows,changes,symbols):
        return [('measured_relocation_binding',candidate)]
    if len(changes) == 2 and (candidate := reciprocal_links(source,part,changes)):
        return [('measured_link_store_order',candidate)]
    return []
