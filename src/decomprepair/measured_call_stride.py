"""Stage a byte index's shift/add stride before the first of two calls."""

import re

from .integer_repair_support import IDENT, NUMBER, calls, edit, integer, split_args, view

# The first shift occupies the guard's delay slot. The relocated base stays in
# v0 until the call delay slot, while the scaled index belongs in a0.
_TARGET = re.compile(
    rf'sll \$a0, \$a1, 1\n'
    rf'lui \$at, %hi\((?P<input>{IDENT})\)\nlwc1 \$\w+, %lo\((?P=input)\)\(\$at\)\n'
    rf'lui \$at, {NUMBER}\nmtc1 \$at, \$\w+\nnop\nmul\.s (?P<result>\$\w+), \$\w+, \$\w+\n'
    rf'lui \$v0, %hi\((?P<base>{IDENT})\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)\n'
    r'addu \$a0, \$a0, \$a1\nsll \$a0, \$a0, 2\n'
    rf'lui \$at, %hi\((?P<output>{IDENT})\)\nswc1 (?P=result), %lo\((?P=output)\)\(\$at\)\n'
    rf'jal (?P<call>{IDENT})\naddu \$a0, \$v0, \$a0'
)
_FIELD = rf'M2C_FIELD\(\s*&{IDENT}\s*,\s*{{kind}}\s*\*,\s*{NUMBER}\s*\)'


def _paired_scale(rows, changed):
    first = changed[0]
    if (first == 0 or changed != [first, first + 7, first + 8, first + 9, first + 10, first + 14]
            or not rows[first - 1][1].startswith(('beq ', 'bne ', 'beqz ', 'bnez '))):
        return None
    target = _TARGET.fullmatch('\n'.join(row[1] for row in rows[first:first + 15]))
    if not target:
        return None
    swap = {'$a0': '$v0', '$v0': '$a0'}
    # The last instruction still writes a0 and merely exchanges its two sources.
    register_changes = [re.sub(r'\$(?:a0|v0)\b', lambda m: swap[m[0]], rows[i][1]) for i in changed[:-1]]
    register_changes.append('addu $a0, $a0, $v0')
    if any(rows[i][0] != 'r' or rows[i][2] != expected for i, expected in zip(changed, register_changes)):
        return None
    if not any(re.fullmatch(r'lbu \$a1, (?:0x0|0)?\(\$s[0-7]\)', row[1]) for row in rows[:first]):
        return None
    following = [row[1][4:] for row in rows[first + 15:] if row[1].startswith('jal ')]
    if len(following) != 1 or following[0] == target['call']:
        return None
    return target['call'], following[0]


def _staged_scale(source, name, header, rows, changed):
    if ('M2C_FIELD' not in source or '__repair_stride_' in source + header
            or not (pair := _paired_scale(rows, changed)) or not (part := view(source, name))):
        return None
    sites = [list(calls(part, callee)) for callee in pair]
    if any(len(found) != 1 for found in sites):
        return None
    (start, end), (later, later_end) = (found[0] for found in sites)
    first = part.clean[start:end]
    second = part.clean[later:later_end]
    operands = split_args(first)
    later_operands = split_args(second)
    if len(operands) != 2 or len(later_operands) != 2 or later <= end:
        return None
    scale = first[slice(*operands[0])]
    index = first[slice(*operands[1])].strip()
    if (not re.fullmatch(_FIELD.format(kind='u8'), index)
            or second[slice(*later_operands[0])].strip() != scale.strip()):
        return None
    product = re.fullmatch(
        rf'\s*(?P<base>{_FIELD.format(kind="s32")})\s*\+\s*'
        rf'\(\s*{re.escape(index)}\s*\*\s*(?P<stride>{NUMBER})\s*\)\s*', scale)
    if not product or integer(product['stride']) != 12:
        return None
    # The float assignment starts the guarded arm. Put declarations at its
    # beginning for the original compiler's C dialect, then split the scale
    # into two statements before the first call and keep the second call intact.
    prefix = part.clean[part.opening + 1:start]
    float_field = _FIELD.format(kind='f32')
    float_product = rf'{float_field}\s*\*\s*\d+\.\d+[fF]'
    rhs = rf'(?:{float_product}|\(f32\)\s*\(\s*{float_product}\s*\))'
    store = re.search(rf'{{\n(?P<indent>[ \t]+){float_field}\s*=\s*{rhs};[ \t]*\n'
                      rf'(?P<call>[ \t]*){pair[0]}\($', prefix)
    if not store or store['indent'] != store['call'] or index not in prefix[:store.start()]:
        return None
    spot = part.opening + 1
    declaration = spot + store.start('indent')
    call_start = spot + store.start('call')
    indent = store['indent']
    return edit(source, [
        (declaration, declaration, f'{indent}s32 __repair_stride_index = {index};\n{indent}s32 __repair_stride_offset;\n'),
        (call_start, call_start,
         f'{indent}__repair_stride_offset = (__repair_stride_index << 1) + __repair_stride_index;\n'
         f'{indent}__repair_stride_offset = __repair_stride_offset << 2;\n'),
        (start, start + operands[0][1], f'{product["base"]} + __repair_stride_offset'),
    ])


def variants(source, name, header, rows, changed):
    if len(changed) == 6 and (candidate := _staged_scale(source, name, header, rows, changed)):
        return [('staged_call_stride', candidate)]
    return []
