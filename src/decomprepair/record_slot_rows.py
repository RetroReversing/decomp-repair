"""A fixed-stride table read through byte arithmetic, written as the typed records the original indexed.

m2c, and the saved sources a search leaves behind, address a table of records as bytes: `table[i * 24]` on a byte array,
`FIELD(table, s32, (e & 0xFFFF) * 24)` (a one-line `(*(T *)((char *)(base) + (offset)))` macro, or m2c's `M2C_FIELD`), or
`*(T *)(table + i * 12)`. The original declared a record of that size, `Row table[]`, and wrote `table[i].f0`.
The spelling changes what GCC 2.7.2 (KMC, `-G0 -mips3 -mgp32 -mfp32 -O2`) builds in two places, and neither is visible in
the instructions of one access:

* a symbol's address read as a pointer plus a byte index is loaded into a pseudo first (`la`), and loop.c hoists that
  `la` out of the loops around it, into a register of its own that the target does not spend (a byte table counted in
  a loop inside a list walk; its saved registers rotated and one address came out as `la` + `lbu 0(reg)` instead of
  `lui`, `addu`, `lbu %lo(table)(at)`). Typed `table[i].f0` is one address expression, and combine keeps the `lui`.
* two straight-line reads of one symbol share one `la` (cse), combine then builds the second read by keeping that load,
  and the first read's address sum stays behind with a reference count and no register class (`ST_REGS`): reload's
  `alter_reg` gives it a stack slot, the frame is eight bytes larger than the target's and nothing reads the slot
  (`.frame ... vars=` 56 against 48; docs/learnings/finding/byte-arithmetic-table-reads-leave-a-frame-hole.md).

Only the first field (offset 0) of a record is recovered, as in `record_slot_table`: every mention of the symbol must be
one access with one stride, the same field type and a stride that is a multiple of its size. The index may hold a call
(it is evaluated once either way). One child per table, and one with every table written as records, because the frame
hole needed three tables (two of them straight-line reads, the third a loop's) changed together.
"""
import re

from .csource import _blank
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'record_slot_rows'
FAMILIES = (FAMILY,)
LIMIT = 8
_SIZES = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'short': 2, 'u32': 4, 's32': 4, 'f32': 4, 'int': 4}
_ONE_BYTE = ('u8', 's8', 'char')
_DECL = re.compile(r'^[ \t]*extern[ \t]+(' + '|'.join(_SIZES) + r')[ \t]+([A-Za-z_]\w*)[ \t]*(?:\[[ \t]*(?:0[xX][0-9a-fA-F]+|\d*)[ \t]*\])?[ \t]*;[ \t]*$', re.M)
_FIELD_MACRO = re.compile(r'^[ \t]*#[ \t]*define[ \t]+(\w+)[ \t]*\(\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\)[ \t]*'
                          r'\(\s*\*\s*\(\s*\3\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(?\s*\2\s*\)?\s*\+\s*\(?\s*\4\s*\)?\s*\)\s*\)\s*$', re.M)


def _macros(clean):
    return {'M2C_FIELD'} | {hit[1] for hit in _FIELD_MACRO.finditer(clean)}


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


_STRIDE = re.compile(r'(.+?)\s*\*\s*(0x[0-9A-Fa-f]+|\d+)\s*\Z', re.S)
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)')


def _split(operand):
    """`(e) * 24` as (e, 24): the stride is the last factor. `e` may call a function (it runs once either way) but may
    not step or assign anything."""
    text = _unwrap(operand)
    hit = _STRIDE.match(text)
    if not hit:
        return None
    left = _unwrap(hit[1])
    if left.count('(') != left.count(')') or _EFFECT.search(left) or not left:
        return None
    return left, int(hit[2], 0)


_LEFT = re.compile(r'\*\s*(\(?)\s*\(\s*(\w+)\s*\*\s*\)\s*((?:\(\s*char\s*\*\s*\)\s*|\(\s*)+)$')
_RIGHT = re.compile(r'\s*(\)*)\s*\+\s*')
_CHAR_CAST = re.compile(r'\(\s*char\s*\*\s*\)')


def _pointer_plus(clean, at, name):
    """`*(T *)(table + e)` and its parenthesised spellings around the mention of `table` at `at`: (start, stop, type, operand
    start, operand stop), or None."""
    left = _LEFT.search(clean[max(0, at - 80):at])
    right = _RIGHT.match(clean, at + len(name))
    if not left or not right:
        return None
    opened = len(_CHAR_CAST.sub('', left[3]).replace(' ', '').replace('\n', ''))
    if len(right[1]) != opened - 1:
        return None
    depth, pos = 0, right.end()
    while pos < len(clean):
        if clean[pos] == '(':
            depth += 1
        elif clean[pos] == ')':
            if depth == 0:
                break
            depth -= 1
        pos += 1
    else:
        return None
    stop = pos + 1
    if left[1]:
        if clean[stop:stop + 1] != ')':
            return None
        stop += 1
    return max(0, at - 80) + left.start(), stop, left[2], right.end(), pos


def _accesses(source, clean, table, kind, decl, macros):
    """Every mention of `table` outside its declaration as (start, stop, index, stride, type); None if one is no access."""
    found = []
    taken = []
    name = re.escape(table)

    def keep(start, stop, operand, typ):
        split = _split(operand)
        if not split or typ not in _SIZES or _SIZES[typ] >= split[1] or split[1] % _SIZES[typ]:
            return False
        found.append((start, stop, split[0], split[1], typ))
        taken.append((start, stop))
        return True

    if macros:
        for hit in re.finditer(r'\b(?:' + '|'.join(map(re.escape, macros)) + r')\s*\(\s*' + name + r'\s*,\s*(\w+)\s*,', clean):
            stop = close(clean, clean.index('(', hit.start()))
            if not stop or not keep(hit.start(), stop, source[hit.end():stop - 1], hit[1]):
                return None
    for mention in re.finditer(r'\b' + name + r'\b', clean):
        if decl[0] <= mention.start() < decl[1] or any(a <= mention.start() < b for a, b in taken):
            continue
        plus = _pointer_plus(clean, mention.start(), table)
        if plus and not keep(plus[0], plus[1], source[plus[3]:plus[4]], plus[2]):
            return None
        if not plus and kind in _ONE_BYTE and clean[mention.end():].lstrip().startswith('['):
            bracket = clean.index('[', mention.end())
            stop = close(clean, bracket, '[', ']')
            if not stop or not keep(mention.start(), stop, source[bracket + 1:stop - 1], kind):
                return None
    mentions = [m.start() for m in re.finditer(r'\b' + name + r'\b', clean) if not decl[0] <= m.start() < decl[1]]
    covered = all(any(a <= m < b for a, b in taken) for m in mentions)
    return found if found and covered and len({use[3] for use in found}) == 1 and len({use[4] for use in found}) == 1 else None


def variants(source, name):
    clean = _blank(source)
    macros = _macros(clean)
    children = []
    for decl in _DECL.finditer(clean):
        kind, table = decl[1], decl[2]
        uses = _accesses(source, clean, table, kind, (decl.start(), decl.end()), macros)
        if not uses:
            continue
        stride, typ = uses[0][3], uses[0][4]
        pad = stride - _SIZES[typ]
        row = f'Row_{table}'
        record = f'typedef struct {{ {typ} f0; u8 pad[{pad}]; }} {row};\nextern {row} {table}[];'
        edits = [(a, b, f'{table}[{index}].f0') for a, b, index, _, _ in uses] + [(decl.start(), decl.end(), record)]
        children.append(edits)
    if not children:
        return []
    result = [edit(source, edits) for edits in children[:LIMIT]]
    if len(children) > 1:
        result.append(edit(source, [item for edits in children for item in edits]))
    return [(FAMILY, text) for text in result if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)
