"""A pointer kept beside another at a fixed distance, written as offsets from the one pointer.

m2c names the second base register of a loop that walks records with two pointers:

    var_a = start;
    var_b = var_a + 0x1E;                      /* a halfword pointer: 0x3C bytes on */
    do {
        ... M2C_FIELD(var_b, u16 *, -0x18) ...  M2C_FIELD(var_b, s32 *, 0) ...
        var_a += 0x22;
        var_b = var_a + 0x1E;
    } while (...);

The game's record pointer was one variable: GCC 2.7.2 picked the second register itself, as the strength reduction of
the field addresses it saw (`lw $v0, -0x18($s2)` off a register 0x3C past the record), and one of its increments sits
before the loop's `bgtz` where the game's does. A user variable for the second base is a pointer of its own: the
compiler keeps it, the increment pair is the source's, and the register order follows the source rather than what the
loop optimizer would have made.

When `var_b` is assigned only `var_a + K`, every assignment of `var_a` after the first of those is followed at once by
the same `var_b = var_a + K;`, and every use of `var_b` is an m2c field read `M2C_FIELD(var_b, T, offset)` with a
literal offset, the variant drops `var_b` and reads `M2C_FIELD(var_a, T, offset + K * size)`. `size` is the byte size
of what `var_a` points to (`u8` 1, `u16` 2, `u32`/`s32`/`f32` 4).
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'derived_pointer_fold'
FAMILIES = (FAMILY,)

SIZES = {'u8': 1, 's8': 1, 'char': 1, 'void': 1, 'u16': 2, 's16': 2, 'short': 2,
         'u32': 4, 's32': 4, 'int': 4, 'f32': 4, 'float': 4}


def _declaration(clean, base, end, name):
    hit = re.search(rf'(?m)^([ \t]*)((?:unsigned\s+)?{IDENT})[ \t]*\*[ \t]*{re.escape(name)}[ \t]*;[ \t]*\n', clean[base:end])
    return (base + hit.start(), base + hit.end(), hit[2].split()[-1]) if hit else None


def _number(text):
    return int(text, 0)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, base, end = part.clean, part.opening + 1, part.end
    result = []
    for derived in re.finditer(rf'(?m)^[ \t]*({IDENT})[ \t]*=[ \t]*({IDENT})[ \t]*\+[ \t]*(0[xX][0-9A-Fa-f]+|\d+)[ \t]*;[ \t]*\n', clean[base:end]):
        low, start, bump = derived[1], derived[2], _number(derived[3])
        if low == start or any(low == other['b'] for other in result):
            continue
        low_decl, start_decl = _declaration(clean, base, end, low), _declaration(clean, base, end, start)
        if not low_decl or not start_decl or start_decl[2] not in SIZES or low_decl[2] != start_decl[2]:
            continue
        # every assignment of `low` is `low = start + K;` with this K
        assignments = list(re.finditer(rf'(?<![\w.>*]){low}[ \t]*(?:[-+*/|&^]|<<|>>)?=(?!=)[^;]*;', clean[base:end]))
        if not assignments or any(not re.fullmatch(rf'{low}[ \t]*=[ \t]*{start}[ \t]*\+[ \t]*{derived[3]}[ \t]*;', a[0]) for a in assignments):
            continue
        first = assignments[0].start()
        # every write of `start` after the first such assignment is followed at once by one
        bad = False
        for step in re.finditer(rf'(?<![\w.>*])(?:{start}[ \t]*(?:[-+*/|&^]|<<|>>)?=(?!=)[^;]*;|(?:\+\+|--){start}\b[^;]*;|{start}(?:\+\+|--)[^;]*;)', clean[base:end]):
            if step.start() <= first:
                continue
            after = clean[base + step.end():base + step.end() + 160].lstrip()
            if not re.match(rf'{low}[ \t]*=[ \t]*{start}[ \t]*\+[ \t]*{derived[3]}[ \t]*;', after):
                bad = True
                break
        if bad or re.search(rf'&\s*{low}\b|&\s*{start}\b', clean[base:end]):
            continue
        # every use of `low` is an m2c field read at a literal offset
        uses = list(re.finditer(rf'M2C_FIELD\(\s*{low}\s*,\s*([^,()]+?)\s*,\s*(-?(?:0[xX][0-9A-Fa-f]+|\d+))\s*\)', clean[base:end]))
        mentions = [m for m in re.finditer(rf'(?<![\w.>]){low}\b', clean[base:end])]
        declared = 1
        if len(mentions) - declared != len(assignments) + len(uses):
            continue
        scaled = bump * SIZES[start_decl[2]]
        edits = []
        for use in uses:
            offset = _number(use[2]) + scaled
            shown = ('-' if offset < 0 else '') + (f'0x{abs(offset):X}' if abs(offset) >= 10 else str(abs(offset)))
            edits.append((base + use.start(), base + use.end(), f'M2C_FIELD({start}, {use[1]}, {shown})'))
        for a in assignments:
            line_start = clean.rfind('\n', 0, base + a.start()) + 1
            line_end = clean.index('\n', base + a.end()) + 1
            edits.append((line_start, line_end, ''))
        edits.append((low_decl[0], low_decl[1], ''))
        result.append({'b': low, 'text': edit(source, edits)})
    return [(FAMILY, item['text']) for item in result]
