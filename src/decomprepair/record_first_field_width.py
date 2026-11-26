"""A record whose first field the target reads narrower than the draft declares it: narrow it, widen the padding.

m2c (or a refined draft) declares the element of a global array as `typedef struct { u16 f0; u8 pad[622]; } Slot;`
when it saw one halfword read, but the target loads `lbu` from every `%lo(D)` of the array: the record's first field is
a byte. gcc's loads, extensions and register choices follow the declared type, so the function scored 200 on that one
row. The record's size has to stay (the index scaling and every other field read), so the field takes the target's
width and the padding grows by what the field gave up: `{ u8 f0; u8 pad[623]; }`.

Offered for each `typedef struct { T f0; u8 pad[N]; } Name;` whose global (`extern Name D[];` or `extern Name D;`)
is reached by the target only with one load (or store) width different from T's, the field's signedness kept for the
same-width case and the load's kind (`lbu` u8, `lb` s8, `lh` s16, ...) otherwise. A record read at several widths
(`fN` at offsets of its own) is left alone: only accesses through the `%lo(D)` of the symbol itself count, and those
are the first field's.
"""
import re

from .csource import _blank
from .field_width_repairs import IDENT, OPS, STORE, SYMBOL, WIDTH

FAMILY = 'record_first_field_width'
FAMILIES = (FAMILY,)
RECORD = re.compile(rf'typedef\s+struct\s*{{\s*(?P<type>{IDENT})\s+(?P<field>{IDENT})\s*;\s*'
                    rf'(?P<pad_type>u8|s8|char|unsigned\s+char)\s+(?P<pad>{IDENT})\s*\[\s*(?P<count>\d+)\s*\]\s*;\s*}}'
                    rf'\s*(?P<name>{IDENT})\s*;')
GLOBAL = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{IDENT})\s+(?P<name>{IDENT})\s*(?:\[[^\]]*\])?\s*;')


def variants(source, name, asm):
    if not asm or name not in source:
        return []
    clean = _blank(source)
    kinds = {}
    for op, symbol in SYMBOL.findall(asm):
        kinds.setdefault(symbol, {}).setdefault(op in STORE, set()).add(OPS[op])
    out = []
    for record in RECORD.finditer(clean):
        was = record['type']
        if was not in WIDTH:
            continue
        users = [g['name'] for g in GLOBAL.finditer(clean) if g['type'] == record['name']]
        seen = set()
        for user in users:
            by = kinds.get(user)
            if by:
                seen |= by.get(False) or by.get(True)
        if len(seen) != 1:
            continue
        kind = next(iter(seen))
        if WIDTH[kind] >= WIDTH[was]:
            continue
        pad = int(record['count']) + WIDTH[was] - WIDTH[kind]
        replacement = (record.group(0)[:record.start('type') - record.start()] + kind
                       + record.group(0)[record.end('type') - record.start():record.start('count') - record.start()]
                       + str(pad) + record.group(0)[record.end('count') - record.start():])
        out.append((FAMILY, source[:record.start()] + replacement + source[record.end():]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 60}
