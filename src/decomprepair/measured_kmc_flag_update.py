"""Recover a bit update that KMC joins at a shared store."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'(?P<branch>bne \$v1, \$v0|beqz \$v0), \d+\naddiu \$v1, \$zero, -5\n'
    r'lw \$v0, (?P<field>\d+)\(\$a0\)\n'
    rf'j (?P<name>{IDENT})\+\d+\nori \$v0, \$v0, 4\n'
    r'lw \$v0, (?P=field)\(\$a0\)\nand \$v0, \$v0, \$v1\n'
    r'(?:jr \$ra\nsw \$v0, (?P=field)\(\$a0\)|sw \$v0, (?P=field)\(\$a0\)\njr \$ra\nnop)'
)
_SOURCE = re.compile(
    rf'(?P<set>(?P<value>{IDENT}) = M2C_FIELD\((?P<object>{IDENT}), s32 \*, (?P<field>{NUMBER})\) \| 4;)\s*'
    r'\}\s*else\s*\{\s*'
    rf'(?P<clear>(?P=value) = M2C_FIELD\((?P=object), s32 \*, (?P=field)\) & ~4;)\s*\}}\s*'
    rf'(?P<store>M2C_FIELD\((?P=object), s32 \*, (?P=field)\) = (?P=value);)'
)


def variants(source, name, header, rows):
    if len(rows) not in (19, 22):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    target_hit = _TARGET.search(target)
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if (not target_hit or target_hit['name'] != name or len(changes) != 4
            or ('addiu $v1, $zero, -5', 'addiu $v0, $zero, -5') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.search(part.body)
    if (not draft or integer(draft['field']) != int(target_hit['field'])
            or len(re.findall(rf'\b{draft["value"]}\b', part.body)) != 4
            or not re.search(rf'\bs32 {draft["value"]};', part.body)
            or not re.search(rf'\bvoid {re.escape(name)}\(void \*{draft["object"]}\)\s*$', part.clean[:part.opening])):
        return []
    field = f'M2C_FIELD({draft["object"]}, s32 *, {draft["field"]})'
    start = part.opening + 1
    fixed = edit(source, [(start + draft.start(key), start + draft.end(key), replacement)
                          for key, replacement in [('set', field + ' |= 4;'), ('clear', field + ' &= ~4;'), ('store', '')]])
    return [('measured_direct_flag_update', fixed)]
