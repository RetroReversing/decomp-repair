"""Restore a word array shared by the fixed Huffman table fills and builder calls."""

import re

from .integer_repair_support import IDENT, NUMBER, integer
from .mips import normalized_integer_lines

BUILDER = 'huft_build'
_BODY = re.compile(
    rf'if \(M2C_FIELD\(&(?P<state>{IDENT}), s32 \*, (?P<lit>{NUMBER})\) == 0\) {{ '
    rf'(?P<reverse>{IDENT}) = 0x8F; (?P<first>{IDENT}) = &sp25C; '
    r'do { \*(?P=first) = 8; (?P=reverse) -= 1; (?P=first) -= 4; } while \((?P=reverse) >= 0\); '
    rf'(?P<counter>{IDENT}) = 0x90; (?P<second>{IDENT}) = &sp260; '
    r'do { \*(?P=second) = 9; (?P=counter) \+= 1; (?P=second) \+= 4; } while \((?P=counter) < 0x100\); '
    + ''.join(rf'if \((?P=counter) < {bound}\) {{ '
              rf'(?P<{pointer}>{IDENT}) = &\(&sp20\[0\]\)\[(?P=counter)\]; '
              rf'do {{ \*(?P={pointer}) = {length}; (?P=counter) \+= 1; (?P={pointer}) \+= 4; }} '
              rf'while \((?P=counter) < {bound}\); }} '
              for pointer, bound, length in (('third', '0x118', 7), ('fourth', '0x120', 8)))
    + rf'(?P<lit_slot>{IDENT}) = (?:\(char \*\))?&(?P=state) \+ (?P<lit_bits>{NUMBER}); '
    r'M2C_FIELD\(&(?P=state), s32 \*, (?P=lit_bits)\) = 7; '
    rf'(?P<lit_result>{IDENT}) = {BUILDER}\(&sp20\[0\], 0x120, 0x101, &(?P<lit_len>{IDENT}), '
    rf'&(?P<lit_extra>{IDENT}), (?P=lit_slot) - 8, (?P=lit_slot)\); (?P<status>{IDENT}) = (?P=lit_result); '
    r'if \((?P=status) != 0\) { M2C_FIELD\((?P=lit_slot), s32 \*, -8\) = 0; return (?P=lit_result); } '
    rf'(?P<fifth>{IDENT}) = &sp20\[0\]; do {{ \*(?P=fifth) = 5; (?P=status) \+= 1; (?P=fifth) \+= 4; }} '
    rf'while \((?P=status) < 0x1E\); (?P<dist_slot>{IDENT}) = (?:\(char \*\))?&(?P=state) \+ (?P<dist_bits>{NUMBER}); '
    r'M2C_FIELD\(&(?P=state), s32 \*, (?P=dist_bits)\) = 5; '
    rf'(?P<dist_result>{IDENT}) = {BUILDER}\(&sp20\[0\], 0x1E, 0, &(?P<dist_len>{IDENT}), '
    rf'&(?P<dist_extra>{IDENT}), (?P=dist_slot) - 8, (?P=dist_slot)\); '
    r'if \((?P=dist_result) >= 2\) { huft_free\(M2C_FIELD\(&(?P=state), s32 \*, (?P=lit)\)\); '
    rf'M2C_FIELD\(&(?P=state), s32 \*, (?P=lit)\) = 0; return (?P=dist_result); }} goto (?P<done>{IDENT}); }} '
    rf'(?P=done): return inflate_codes\(M2C_FIELD\(&(?P=state), s32 \*, (?P=lit)\), '
    rf'M2C_FIELD\(&(?P=state), s32 \*, (?P<dist>{NUMBER})\), M2C_FIELD\(&(?P=state), s32 \*, (?P=lit_bits)\), '
    r'M2C_FIELD\(&(?P=state), s32 \*, (?P=dist_bits)\)\) != 0;'
)


def evidence(rows):
    """Confirm the shared stack slot and both passes through the length table."""
    calls = [line for line in rows if line.startswith(('jal ', 'jalr '))]
    required = {
        'addiu $sp, $sp, -1200', 'sw $s0, 1184($sp)', 'addiu $v0, $sp, 604', 'addiu $v1, $sp, 608',
        'addiu $s0, $zero, 143', 'addiu $s0, $zero, 144', 'addiu $v0, $v0, -4', 'addiu $v1, $v1, 4',
        'slti $v0, $s0, 256', 'slti $v0, $s0, 280', 'slti $v0, $s0, 288', 'slti $v0, $s0, 30',
        'addiu $a1, $zero, 288', 'addiu $a1, $zero, 30', 'addiu $a2, $zero, 257',
    }
    return (calls == [f'jal {BUILDER}', f'jal {BUILDER}', 'jal huft_free', 'jal inflate_codes']
            and required.issubset(rows) and rows.count('addiu $a0, $sp, 32') == 2
            and rows.count('addu $s0, $v0, $zero') == 2)


def applies(lines):
    return evidence(normalized_integer_lines(lines))


def rewrite(part, name, loc, body, end, lines):
    match = _BODY.fullmatch(body)
    if not match or not re.search(rf'\bs32\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]):
        return None
    types = dict.fromkeys(('sp25C', 'sp260', *(match[key] for key in
                          ('reverse', 'counter', 'status', 'lit_result', 'dist_result'))), 's32')
    types.update(dict.fromkeys((match[key] for key in ('first', 'second', 'third', 'fourth', 'fifth')), 's32*'))
    types.update(dict.fromkeys((match['lit_slot'], match['dist_slot']), 'void*'))
    if len(types) != 14 or types != loc:
        return None
    state = match['state']
    rows = normalized_integer_lines(lines)
    for key in ('lit', 'dist', 'lit_bits', 'dist_bits'):
        if not any(f'%lo({state} + {integer(match[key])})' in row for row in rows):
            return None
    if not evidence(rows):
        return None
    for key in ('lit_len', 'lit_extra', 'dist_len', 'dist_extra'):
        if not any(f'%lo({match[key]})' in row for row in rows):
            return None
    lit, dist, lit_bits, dist_bits = (match[key] for key in ('lit', 'dist', 'lit_bits', 'dist_bits'))
    if [integer(x) - integer(lit) for x in (dist, lit_bits, dist_bits)] != [4, 8, 12]:
        return None
    i, lengths = '__m2c_copy_index', '__m2c_copy_lengths'
    left, right = match['lit_slot'], match['dist_slot']
    fills = ''.join(f'        for ({start}; {i} < {bound}; {i}++) {lengths}[{i}] = {width};\n'
                    for start, bound, width in ((f'{i} = 0', 144, 8), ('', 256, 9), ('', 280, 7), ('', 288, 8)))
    return part.source[:part.opening+1] + f'''
    s32 {lengths}[288];
    s32 {i};
    void *{left};
    void *{right};

    if (M2C_FIELD(&{state}, s32 *, {lit}) == 0) {{
{fills}        {left} = (char *)&{state} + {lit_bits};
        M2C_FIELD(&{state}, s32 *, {lit_bits}) = 7;
        {i} = {BUILDER}({lengths}, 0x120, 0x101, &{match['lit_len']}, &{match['lit_extra']}, {left} - 8, {left});
        if ({i} != 0) {{
            M2C_FIELD({left}, s32 *, -8) = 0;
            return {i};
        }}
        for (; {i} < 30; {i}++) {lengths}[{i}] = 5;
        {right} = (char *)&{state} + {dist_bits};
        M2C_FIELD(&{state}, s32 *, {dist_bits}) = 5;
        {i} = {BUILDER}({lengths}, 0x1E, 0, &{match['dist_len']}, &{match['dist_extra']}, {right} - 8, {right});
        if ({i} >= 2) {{
            huft_free(M2C_FIELD(&{state}, s32 *, {lit}));
            M2C_FIELD(&{state}, s32 *, {lit}) = 0;
            return {i};
        }}
        goto {match['done']};
    }}
{match['done']}:
    return inflate_codes(M2C_FIELD(&{state}, s32 *, {lit}), M2C_FIELD(&{state}, s32 *, {dist}),
                         M2C_FIELD(&{state}, s32 *, {lit_bits}), M2C_FIELD(&{state}, s32 *, {dist_bits})) != 0;
}}''' + part.source[end+1:]
