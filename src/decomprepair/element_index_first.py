"""A global array's element `T[i]` written with the scaled index first: `*(s32 *)((i << 2) + (u8 *)T)`.

`T[i]` expands the table's address (`lui`/`addiu`) before the index's shift, so the first scheduler (backwards, the
launch priority of single-set pseudos) meets the shift last and leaves it nearest the add, and local-alloc, which ranks
the short-lived values of a block by references over live length, gives the shift the first free register: the base
takes the next. Written as `(i << 2) + (u8 *) T` the shift is expanded first: on a 182-instruction SN64 GCC 2.8.1
allocator (`-G0 -mips3 -O2 -mfp64`) a store `D[i] = (s32) (buf + size);` before a call took the target's registers
for its base (`$v0`) and index (`$v1`) this way, 145 -> 120; `i * 4 + (u8 *) T` changed nothing (145), so the shift
is offered first. The scheduling reading is from the `-dS` dumps; the judge decides.

element_index_first
    Each `NAME[E]` (NAME a file-scope array of a 1-, 2- or 4-byte integer type, E free of side effects) becomes
    `(*(TYPE *)((E << K) + (u8 *)NAME))` and, as a second child, `(*(TYPE *)((E * SIZE) + (u8 *)NAME))`; one child per
    occurrence and form, at most 16.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'element_index_first'
FAMILIES = (FAMILY,)
LIMIT = 16
SIZES = {'s32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'signed int': 4, 'long': 4, 'unsigned long': 4,
         's16': 2, 'u16': 2, 'short': 2, 'unsigned short': 2, 'signed short': 2,
         's8': 1, 'u8': 1, 'char': 1, 'unsigned char': 1, 'signed char': 1}


def _arrays(context):
    found = {}
    for hit in re.finditer(rf'(?m)^\s*(?:extern\s+|static\s+)?((?:unsigned\s+|signed\s+)?{IDENT})\s+({IDENT})\s*\[[^\]]*\]\s*;',
                           context):
        spelling = ' '.join(hit[1].split())
        if spelling in SIZES:
            found.setdefault(hit[2], set()).add(spelling)
    return {name: types.pop() for name, types in found.items() if len(types) == 1}


def _pure(text):
    return (bool(text.strip()) and not re.search(r'\+\+|--|,|(?<![=!<>])=(?!=)|[;{}?]', text)
            and not re.search(rf'\b{IDENT}\s*\(', text))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    arrays = _arrays(_blank(header or '') + '\n' + clean[:part.opening])
    if not arrays:
        return []
    body_locals = set(re.findall(rf'\b{IDENT}\s+\**\s*({IDENT})\s*[;=\[]', part.body))
    out = []
    for hit in re.finditer(rf'(?<![\w.>&])({IDENT})\s*\[', clean[part.opening:part.end]):
        array = hit[1]
        if array not in arrays or array in body_locals:
            continue
        open_at = part.opening + hit.end() - 1
        depth, close_at = 0, None
        for at in range(open_at, part.end):
            if clean[at] == '[':
                depth += 1
            elif clean[at] == ']':
                depth -= 1
                if depth == 0:
                    close_at = at
                    break
        if close_at is None or clean[close_at + 1:close_at + 2] == '[':
            continue
        index = source[open_at + 1:close_at].strip()
        if not _pure(clean[open_at + 1:close_at]) or clean[part.opening + hit.start() - 1:part.opening + hit.start()] == '&':
            continue
        if not re.fullmatch(rf'{IDENT}|\d+', index):
            index = f'({index})'  # `i + 1` scaled is `(i + 1) * 4`, never `i + 1 * 4`
        typ = arrays[array]
        size = SIZES[typ]
        shift = size.bit_length() - 1
        forms = [f'({index} << {shift}) + (u8 *){array}', f'({index} * {size}) + (u8 *){array}'] if size > 1 else \
            [f'{index} + (u8 *){array}']
        for form in forms:
            result = edit(source, [(part.opening + hit.start(), close_at + 1, f'(*({typ} *)({form}))')])
            if result != source and (FAMILY, result) not in out:
                out.append((FAMILY, result))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 91}  # no wiring
