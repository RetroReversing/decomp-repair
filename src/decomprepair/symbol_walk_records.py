"""A pointer stepped across part of a global array until an end address, written as an index over an array of records.

m2c writes a loop over `table[16] .. table[47]` as the pointer the compiler made for it:

    var = table + 0xC0;                                      index = 16;
    do {                                                     do {
        M2C_FIELD(var, s32 *, 0) = -1;                           ((table_row *) table)[index].unk0 = -1;
        M2C_FIELD(var, s32 *, 8) = 0;                  ->        ((table_row *) table)[index].unk8 = 0;
        var += 0xC;                                              index++;
    } while ((u32) var < (u32) (table + 0x240));             } while (index < 48);

The user pointer is a variable of its own, set where the source sets it. The loop pass makes its pointer and end
address from an indexed loop after the constants it hoists, with the table's base shared between the two, which no
spelling of the walk gives. `pointer_walk_to_index` needs a counter beside the pointer; this loop has none.

The record has the members the loop names (padded to the stride) and the index is unsigned, as the pointer comparison
was. On an 84-instruction N64 table-setup loop (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) this took the draft with its cursor
reads repaired from 1840 to 270 (one function). The candidate is never a verdict: the judge decides."""
import re

from .hoisted_invariant_inline import _loops
from .integer_repair_support import IDENT, NUMBER, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'symbol_walk_records'
FAMILIES = (FAMILY,)
_SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4}
_BYTES = r'(?:s8|u8|char)'
_SET = re.compile(rf'(?<=[;{{}}])\s*(?P<p>{IDENT})\s*=\s*&?(?P<sym>{IDENT})\s*\+\s*(?P<start>{NUMBER})\s*;')
_FIELD = r'M2C_FIELD\(\s*{p}\s*,\s*(?P<type>[suf](?:8|16|32))\s*\*\s*,\s*(?P<offset>{number})\s*\)'
LIMIT = 4


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _record(tag, members, stride):
    lines, at = [], 0
    for offset, kind in sorted(members.items()):
        if offset < at or offset % _SIZES[kind] or offset + _SIZES[kind] > stride:
            return None
        if offset > at:
            lines.append(f'    u8 pad{at:X}[{offset - at}];')
        lines.append(f'    {kind} unk{offset:X};')
        at = offset + _SIZES[kind]
    if stride > at:
        lines.append(f'    u8 pad{at:X}[{stride - at}];')
    return 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\n'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for setup in _SET.finditer(clean, part.opening, part.end):
        pointer, symbol = setup['p'], setup['sym']
        if not re.search(rf'\bextern\s+{_BYTES}\s+{symbol}\s*\[\s*\]\s*;', clean):
            continue
        declared = re.search(rf'\b(?:void|{_BYTES})\s*\*\s*{pointer}\s*;', clean[part.opening:part.end])
        if not declared or _address_taken(clean[part.opening:part.end], pointer):
            continue
        do = re.search(r'\bdo\s*\{', clean[setup.end():part.end])
        if not do:
            continue
        brace = setup.end() + do.end() - 1
        end = close(clean, brace, '{', '}')
        if end is None or end > part.end:
            continue
        test = re.compile(rf'\s*while\s*\(\s*\(\s*u32\s*\)\s*{pointer}\s*<\s*\(\s*u32\s*\)\s*\(\s*&?{symbol}\s*\+\s*'
                          rf'(?P<limit>{NUMBER})\s*\)\s*\)\s*;').match(clean, end)
        body_end = clean.rfind('}', brace, end)
        step = re.search(rf'(?<=[;{{}}])\s*{pointer}\s*\+=\s*(?P<stride>{NUMBER})\s*;\s*\Z', clean[:body_end])
        if not test or not step or step.start() < brace:
            continue
        first, stride, limit = _number(setup['start']), _number(step['stride']), _number(test['limit'])
        if not stride or first % stride or limit % stride or limit <= first:
            continue
        field = re.compile(_FIELD.format(p=pointer, number=NUMBER))
        uses = list(field.finditer(clean, brace, step.start()))
        # the declaration, the set, the step (once or twice, `p += K`), the test and each field are all the mentions
        if not uses or len(re.findall(rf'\b{pointer}\b', clean[part.opening:part.end])) != len(uses) + 4:
            continue
        nested = _loops(clean, brace + 1, body_end)   # a nested loop's own `continue` is not this loop's
        if any(not any(a < hit.start() < b for a, b in nested)
               for hit in re.compile(r'\bcontinue\b').finditer(clean, brace, body_end)):
            continue
        members = {}
        for use in uses:
            if members.setdefault(_number(use['offset']), use['type']) != use['type']:
                break
        else:
            tag, index = f'{symbol}_row', f'{pointer}_index'
            record = _record(tag, members, stride)
            if record is None or re.search(rf'\b(?:{tag}|{index})\b', clean):
                continue
            changes = [(use.start(), use.end(), f'(({tag} *) {symbol})[{index}].unk{_number(use["offset"]):X}')
                       for use in uses]
            changes.append((setup.start('p'), setup.end(), f'{index} = {first // stride};'))
            body_close = step.end()
            changes.append((step.start() + len(step.group()) - len(step.group().lstrip()), body_close,
                            f'{index}++;\n    '))
            changes.append((test.start() + len(test.group()) - len(test.group().lstrip()), test.end(),
                            f'while ({index} < {limit // stride});'))
            changes.append((part.opening + 1, part.opening + 1, f'\n    u32 {index};'))
            function = clean.rfind('\n', 0, part.opening)
            definition = list(re.finditer(rf'(?m)^[^\n;{{}}#]*\b{name}\s*\(', clean[:part.opening]))
            at = definition[-1].start() if definition else function + 1
            changes.append((at, at, record))
            out.append((FAMILY, edit(source, changes)))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
