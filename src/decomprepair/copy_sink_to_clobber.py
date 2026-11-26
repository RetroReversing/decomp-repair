"""A copy of a variable (`ch = c;`) moved down to just before the statement that overwrites the variable
(`ch = c; c = table[c];`), when nothing between reads or writes the copy and nothing writes the variable.

On a 398-instruction SN64 GCC 2.8.1 glyph printer (`-G0 -mips3 -O2`) the byte copy of the character parameter,
`ch = c;`, was the function's first statement; `ch` is spilled, and its `sb $s0, 0x20($sp)` follows the copy's place.
The target stores it after the first texture words, just before `lbu $s0` reloads the parameter's register: the copy
was made where `c` is reused for the glyph (`ch = c; c = D_800B2904[c];`). Moved there, 330 -> 0 after
`mask_in_place`. The spill-placement reading is a hypothesis; the judge decides.

copy_sink_to_clobber
    A statement `L = P;` (L and P plain identifiers, neither address-taken, in a function with no labels or gotos)
    and, later in the same block, the first statement that assigns P (`P = ...;`, `P += ...;`, `P++;`). When no
    statement between them names L and none writes P, the copy moves to just before that statement. One child per
    copy; at most 16.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view

FAMILY = 'copy_sink_to_clobber'
FAMILIES = (FAMILY,)
LIMIT = 16
COPY = re.compile(rf'\s*({IDENT})\s*=\s*({IDENT})\s*;\s*')
JUMPS = re.compile(r'\bgoto\b|(?m:^[ \t]*(?!case\b|default\b)[A-Za-z_]\w*[ \t]*:(?!:))')


def _writes(text, variable):
    v = re.escape(variable)
    return re.search(rf'(?<![\w.>])(?:\+\+|--)\s*{v}\b|(?<![\w.>]){v}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))', text)


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end - 1]
    if JUMPS.search(body):
        return []
    pairs = brace_pairs(clean, part.opening, part.end)
    blocks = [(part.opening, part.end - 1)] + sorted((o, c) for o, c in (pairs or {}).items() if o != part.opening)
    out = []
    for opening, closing in blocks:
        spans = statements(clean, opening + 1, closing)
        for index, (start, end) in enumerate(spans):
            hit = COPY.fullmatch(clean[start:end])
            if not hit or hit[1] == hit[2]:
                continue
            local, variable = hit[1], hit[2]
            if re.search(rf'&\s*(?:{re.escape(local)}|{re.escape(variable)})\b', body):
                continue
            for later in range(index + 1, len(spans)):
                text = clean[spans[later][0]:spans[later][1]]
                if re.match(rf'\s*{re.escape(variable)}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))', text):
                    if later == index + 1:
                        break
                    line = source.rfind('\n', 0, start) + 1
                    stop = source.find('\n', end)
                    stop = len(source) if stop < 0 else stop + 1
                    whole = not source[line:start].strip() and not source[end:stop].strip()
                    removal = (line, stop, '') if whole else (start, end, '')
                    target_line = source.rfind('\n', 0, spans[later][0]) + 1
                    indent = re.match(r'[ \t]*', source[target_line:])[0]
                    copy = source[start:end].strip()
                    result = edit(source, [removal, (spans[later][0], spans[later][0], f'{copy}\n{indent}')])
                    if result != source and (FAMILY, result) not in out:
                        out.append((FAMILY, result))
                    break
                if re.search(rf'\b{re.escape(local)}\b', text) or _writes(text, variable):
                    break
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # registry: no wiring
