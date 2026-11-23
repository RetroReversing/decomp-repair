"""One-member records that hold a field read or written through `((Record *) p)->value`, written back as plain pointer casts.

A search that wanted a field load to float above an earlier store to a scalar global (`field_struct_view`,
`single_field_record`) types the field as the only member of a record: `typedef struct { unsigned char pad[44]; f32
value; } Rec2C;` and `((Rec2C *) p)->value`. GCC 2.7.2 marks such a load as a member of a struct (`MEM_IN_STRUCT_P`),
and sched.c's `true_dependence` then says it cannot conflict with a store to a scalar global at a fixed address
(`! (MEM_IN_STRUCT_P (x) && rtx_addr_varies_p (x) && ... ! MEM_IN_STRUCT_P (mem) && ! rtx_addr_varies_p (mem))`): the
load is hoisted above the global store. A load written `*(f32 *)((char *) p + 0x2C)` is not a member and stays behind
that store, in source order. The hoist is right for the functions that needed it and wrong for the ones that did not:
a 603-instruction N64 state machine (KMC GCC 2.7.2) carried the member form on seven sites (the vector it saves to three
globals, then zeroes), and every one of them was one instruction too early; written as plain casts, all seven at once,
the function went from 1370 to 415 (the other rows were then register choices). One site alone changes nothing the
judge can see when its neighbours stay hoisted, which is why a child writes every site of a record at once.

`target_local_repairs.records` already offers the inverse for records whose member is `field_XX`; this reads the
`value` (or `v`) member that its `single_field_record` writes, and any other record that is only an optional byte pad
and one member.

Proposals, labelled `record_member_plain`: every site of one record, for each record; every site of every record;
and each single site (stores first), up to a limit. The record's typedef stays (an unused typedef is harmless).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'record_member_plain'
FAMILIES = (FAMILY,)
LIMIT = 12

_ID = r'[A-Za-z_]\w*'
_TYPEDEF = re.compile(
    rf'typedef\s+struct\s*(?:{_ID})?\s*\{{\s*(?:(?:unsigned\s+char|char|u8|s8)\s+{_ID}\s*\[\s*(?P<pad>0[xX][0-9A-Fa-f]+|\d+)\s*\]\s*;\s*)?'
    rf'(?P<type>[A-Za-z_][\w \t]*?(?:\s*\*+)?)\s*(?P<member>{_ID})\s*;\s*\}}\s*(?P<name>{_ID})\s*;')


def _records(clean, before):
    """{name: (offset, type, member)} of the one-member records declared before the function."""
    found = {}
    for m in _TYPEDEF.finditer(clean[:before]):
        offset = int(m['pad'], 0) if m['pad'] else 0
        kind = re.sub(r'\s+', ' ', m['type']).strip()
        if kind in ('struct', 'union', 'typedef'):
            continue
        found[m['name']] = (offset, kind, m['member'])
    return found


def _operand(clean, start):
    """The pointer expression after `(Record *)`: an identifier, or a parenthesised expression."""
    if start < len(clean) and clean[start] == '(':
        end = close(clean, start)
        return (start, end) if end else None
    m = re.compile(rf'{_ID}').match(clean, start)
    return (m.start(), m.end()) if m else None


def _sites(source, clean, opening, closing, records):
    sites = []
    for name, (offset, kind, member) in records.items():
        for m in re.finditer(rf'\(\(\s*{re.escape(name)}\s*\*\s*\)\s*', clean[opening:closing]):
            start = opening + m.end()
            operand = _operand(clean, start)
            if not operand:
                continue
            after = re.compile(rf'\s*\)?\s*->\s*{re.escape(member)}\b').match(clean, operand[1])
            if not after:
                continue
            # the pointer cast was `((Record *) p)`: its closing parenthesis is first in `after`
            text = clean[operand[1]:after.end()]
            if ')' not in text.split('->')[0]:
                continue
            base = source[operand[0]:operand[1]]
            sites.append((opening + m.start(), after.end(), name, f'*(({kind} *) (((char *) {base}) + 0x{offset:X}))'))
    return sorted(sites)


def _written(clean, end):
    return bool(re.match(r'\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', clean[end:end + 6]))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    records = _records(clean, span[0])
    if not records:
        return []
    sites = _sites(source, clean, opening, closing, records)
    if not sites:
        return []

    def build(group):
        new = source
        for start, end, _, text in sorted(group, reverse=True):
            new = new[:start] + text + new[end:]
        return new

    groups = []
    for record in records:
        same = [site for site in sites if site[2] == record]
        if same:
            groups.append(same)
    if len(groups) > 1:
        groups.append(sites)
    singles = sorted(sites, key=lambda site: (not _written(clean, site[1]), site[0]))
    groups.extend([site] for site in singles)
    out, seen = [], set()
    for group in groups:
        new = build(group)
        if new != source and new not in seen:
            seen.add(new)
            out.append((FAMILY, new))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
