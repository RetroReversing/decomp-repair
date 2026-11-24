"""Three float member copies in a row (x, y, z) written as the one struct assignment the game made.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions: the target copies
vectors between an object's members and frame locals with three `lw` and three `sw` (a struct assignment, moved as
words), where m2c's draft copies them as three `f32` assignments (`lwc1`/`swc1`, one float register each). Each such
copy between a member and a frame local written as `*(F32x3 *)dst = *(F32x3 *)src;` took its rows out, and the four
such copies together moved the score more than the sum of each alone (19868 -> 14293; alone: -1200, -1840, -1110,
-1425), because the float registers they freed changed the allocation around them. Copies between two frame locals
stayed float copies in the same function (each one alone was worse), so the two kinds are offered apart. `word_block_copy` does this for `s32` `M2C_FIELD` words only, so a float vector
copy was never offered.

float_triple_struct_copy
    Three consecutive statements `D(o) = S(p); D(o + 4) = S(p + 4); D(o + 8) = S(p + 8);` whose sides are `f32` cells
    at consecutive addresses become `*(F32x3 *)&D(o) = *(F32x3 *)&S(p);`. A cell is a raw member
    (`*(f32 *)((char *)(P) + O)` or `M2C_FIELD(P, f32 *, O)`), a frame-struct member named by its stack offset
    (`local.sp40`, `local.sp44`, `local.sp48`: m2c's names, so consecutive names are adjacent words) or three elements
    of an array (`local.hit50[0..2]`, `v[0..2]`). Children: every copy at once, every copy that has a pointer member
    on one side (the combination that paid off), every copy between frame locals only, then each copy alone. `F32x3` is declared before the function when the
    source does not have it.

Hypothesis from the match, not from the compiler source: an aggregate assignment of a 12-byte record is expanded as
word moves through integer registers, a float assignment as float loads and stores. The exact judge decides.
"""
import re

FAMILY = 'float_triple_struct_copy'
FAMILIES = (FAMILY,)
LIMIT = 12
RECORD = 'F32x3'
TYPEDEF = f'typedef struct {{ f32 x, y, z; }} {RECORD};\n'

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_RAW = re.compile(
    rf'\(?\s*\*\s*\(\s*f32\s*\*\s*\)\s*\(\s*\(\s*(?:char|u8|s8)\s*\*\s*\)\s*\(?\s*(?P<base>{_ID})\s*\)?\s*'
    rf'(?:\+\s*(?P<off>{_NUM})\s*)?\)\s*\)?')
_FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{_ID})\s*,\s*f32\s*\*\s*,\s*(?P<off>{_NUM})\s*\)')
_SPMEMBER = re.compile(rf'(?P<base>{_ID})\.sp(?P<off>[0-9A-Fa-f]+)')
_ELEMENT = re.compile(rf'(?P<base>{_ID}(?:\.{_ID})?)\s*\[\s*(?P<idx>\d)\s*\]')
_STATEMENT = re.compile(r'(?P<indent>[ \t]*)(?P<lhs>[^=;{}]+?)\s*=\s*(?:\(\s*f32\s*\)\s*)?(?P<rhs>[^=;{}]+?)\s*;[ \t]*$')


def _cell(text):
    """(key, base, offset, address) for one f32 cell, or None."""
    text = text.strip()
    for pattern, kind in ((_RAW, 'raw'), (_FIELD, 'raw')):
        found = pattern.fullmatch(text)
        if found:
            base = found.group('base')
            off = int(found.group('off') or '0', 0)
            return (kind, base), off, f'((char *)({base}) + 0x{off:X})'
    found = _SPMEMBER.fullmatch(text)
    if found:
        off = int(found.group('off'), 16)
        return ('sp', found.group('base')), off, f'&{text}'
    found = _ELEMENT.fullmatch(text)
    if found:
        return ('el', found.group('base')), 4 * int(found.group('idx')), f'&{text}'
    return None


def _assignment(line):
    found = _STATEMENT.fullmatch(line)
    if not found:
        return None
    lhs, rhs = _cell(found.group('lhs')), _cell(found.group('rhs'))
    if lhs is None or rhs is None:
        return None
    return found.group('indent'), lhs, rhs


def _copies(lines):
    """(first line index, replacement line, touches a pointer member) for each run of three adjacent float copies."""
    found, i = [], 0
    while i + 2 < len(lines):
        parts = [_assignment(lines[i + k]) for k in range(3)]
        if all(parts) and _consecutive(parts):
            indent, lhs, rhs = parts[0]
            if lhs[0] != rhs[0] or lhs[1] != rhs[1]:
                member = lhs[0][0] == 'raw' or rhs[0][0] == 'raw'
                found.append((i, f'{indent}*({RECORD} *){lhs[2]} = *({RECORD} *){rhs[2]};', member))
                i += 3
                continue
        i += 1
    return found


def _consecutive(parts):
    for side in (1, 2):
        key, off = parts[0][side][0], parts[0][side][1]
        for k in (1, 2):
            if parts[k][side][0] != key or parts[k][side][1] != off + 4 * k:
                return False
    return True


def _apply(lines, chosen):
    out = list(lines)
    for i, text, _member in sorted(chosen, reverse=True):
        out[i:i + 3] = [text]
    return out


def _with_record(source, name, original):
    if re.search(rf'\b{RECORD}\b', original):
        return source
    found = re.search(rf'(?m)^[^\n;{{}}]*\b{re.escape(name)}\s*\(', source) if name else None
    at = found.start() if found else 0
    return source[:at] + TYPEDEF + source[at:]


def variants(source, name):
    lines = source.split('\n')
    copies = _copies(lines)
    if not copies:
        return []
    members = [c for c in copies if c[2]]
    frame = [c for c in copies if not c[2]]
    sets = [list(copies), members, frame] + [[c] for c in copies]
    result, seen = [], set()
    for chosen in sets:
        text = _with_record('\n'.join(_apply(lines, chosen)), name, source)
        if chosen and text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
