"""m2c's one-word locals that name the start of a copied record, retyped as the records the game copied into.

A function that starts by copying two tables to locals (`Ids ids = gIds; Files files = gFiles;`) can come back from
m2c with the frame as `u8 sp[N]` plus one `s32 spXX` per record's first word, each copy's loop writing through
`&spXX`, the later elements read as `(&spXX)[i]` and a byte of the second record as
`M2C_FIELD((sp + i), u8 *, 0x108)`:

    u8 sp[256];                                              __repair_blockF4w sp10;
    s32 sp10;                                                __repair_block33 sp108;
    s32 sp108;                                          ->
    ... copy loops into &sp10 and &sp108 ...                 sp10 = *(__repair_blockF4w *)(&gIds);
    if (sp10 != arg0) ... (&sp10)[i] ...                     if (sp10.data[0] != arg0) ... sp10.data[i] ...
    M2C_FIELD((sp + i), u8 *, 0x108)                         sp108.data[i]

No step alone helps: with only the copies written as assignments the destination is a four-byte local and the scratch
array still sizes the frame. So the child does all of it: every copy loop becomes an assignment
(`block_move_struct_assign`), each local the copies fill becomes the record, declared in stack order, every access is
spelled through it, and the scratch array goes. Declined when `sp` or a slot is used in any other way.
(`scratch_frame_records` is the same step for m2c's `#define` slot form.)

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 routine (230 instructions) that copies a 61-word table and a
51-byte table to its frame and looks an id up in the first.

The stack's layout following the declaration order is a hypothesis; the judge decides.
"""
import re

from . import block_move_struct_assign
from .csource import _blank, find

FAMILY = 'slot_scalar_records'
FAMILIES = (FAMILY,)

_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_COPY = re.compile(
    r'(?m)^(?P<indent>[ \t]*)\*\((?P<record>__repair_block(?P<size>[0-9A-F]+)w?) \*\)\(&(?P<slot>sp(?P<at>[0-9A-F]+))\)'
    r' = (?=\*\((?P=record) \*\))')
_ARRAY = re.compile(r'(?m)^[ \t]*(?:u8|s8|char|unsigned char)\s+sp\s*\[\s*' + _NUM + r'\s*\]\s*;[ \t]*\n')


def _byte_read(body, records):
    """`M2C_FIELD((sp + i), u8 *, 0x108)` as the byte record's element, or None when one reads elsewhere."""
    pattern = re.compile(
        r'M2C_FIELD\(\s*\(?\s*sp\s*\+\s*(?P<index>\w+)\s*\)?\s*,\s*(?P<type>[su]8)\s*\*\s*,\s*(?P<at>' + _NUM + r')\s*\)')
    bad = []

    def spell(m):
        at = int(m['at'], 0)
        for slot, (start, size, words) in records.items():
            if not words and start <= at < start + size:
                index = m['index'] if at == start else f'{m["index"]} + {at - start}'
                element = f'{slot}.data[{index}]'
                return element if m['type'] == 'u8' else f'(s8){element}'
        bad.append(m)
        return m.group()

    body = pattern.sub(spell, body)
    return None if bad else body


def variants(source, name):
    if not _ARRAY.search(source) or not find(source, name):
        return []
    text = source
    for _ in range(8):
        children = block_move_struct_assign.variants(text, name)
        if not children:
            break
        text = children[0][1]
    span = find(text, name)
    if not span:
        return []
    body = text[span[0]:span[1]]
    records, declarations = {}, {}
    for copy in _COPY.finditer(body):
        slot = copy['slot']
        declared = list(re.finditer(rf'(?m)^(?P<indent>[ \t]*)(?:s32|u32|int|M2C_UNK|s8|u8)\s+{slot}\s*;[ \t]*\n', body))
        if slot in records or len(declared) != 1:
            return []
        records[slot] = (int(copy['at'], 16), int(copy['size'], 16), copy['record'].endswith('w'))
        declarations[slot] = copy['record']
    ordered = sorted(records, key=lambda slot: records[slot][0])
    if not ordered or any(records[a][0] + records[a][1] > records[b][0] for a, b in zip(ordered, ordered[1:])):
        return []

    body = _COPY.sub(lambda m: f'{m["indent"]}{m["slot"]} = ', body)
    marker = '\x00records\x00\n'
    for number, slot in enumerate(ordered):
        body = re.sub(rf'(?m)^[ \t]*(?:s32|u32|int|M2C_UNK|s8|u8)\s+{slot}\s*;[ \t]*\n', marker if not number else '', body)
    array = _ARRAY.search(body)
    if not array:
        return []
    indent = re.match(r'[ \t]*', array.group())[0]
    body = body[:array.start()] + body[array.end():]
    body = body.replace(marker, ''.join(f'{indent}{declarations[slot]} {slot};\n' for slot in ordered))
    body = _byte_read(body, records)
    if body is None:
        return []
    for slot in ordered:
        assigned = rf'(?m)^[ \t]*{declarations[slot]} {slot};\n|^[ \t]*{slot} = \*\({declarations[slot]} \*\)[^\n]*\n'
        kept, last, pieces = [], 0, []
        for line in re.finditer(assigned, body):
            pieces.append(body[last:line.start()])
            kept.append(line.group())
            last = line.end()
        pieces.append(body[last:])
        spelled = []
        for piece in pieces:
            piece = re.sub(rf'\(\s*&\s*{slot}\s*\)\s*\[', f'{slot}.data[', piece)
            piece = re.sub(rf'&\s*{slot}\b(?!\s*[.\[])', f'{slot}.data', piece)
            piece = re.sub(rf'\b{slot}\b(?!\s*\.data)', f'{slot}.data[0]', piece)
            spelled.append(piece)
        body = ''.join(a + b for a, b in zip(spelled, kept + ['']))
    if re.search(r'\bsp\b', _blank(body)):
        return []
    result = text[:span[0]] + body + text[span[1]:]
    return [(FAMILY, result)] if result != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
