"""Correct scaled word pointers when the target indexes records by bytes."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'sll \$v1, \$s0, 1\naddu \$v1, \$v1, \$s0\nsll \$v1, \$v1, 5\n'
    r'addu \$v1, \$v1, \$s0\nsll \$v1, \$v1, 2\n'
    rf'lui \$a0, %hi\((?P<base>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=base)\)\n'
    rf'addu \$a0, \$v1, \$a0\nlui \$at, %hi\((?P<out>{IDENT})\)\n'
    rf'addu \$at, \$at, \$v1\nsw \$v0, %lo\((?P=out)\)\(\$at\)'
)
_SOURCE = re.compile(
    rf'(?P<decl>\bs32\s+(?P<offset>{IDENT})\s*;)'
    rf'(?P<middle>[\s\S]*?)\b(?P=offset)\s*=\s*(?P<index>{IDENT})\s*\*\s*0x184\s*;\s*'
    rf'\*\(\s*&(?P<out>{IDENT})\s*\+\s*(?P=offset)\s*\)\s*=\s*'
    rf'(?P<allocator>{IDENT}\s*\([^;{{}}]*\))\s*;\s*'
    rf'(?P<call>{IDENT})\s*\(\s*(?P=offset)\s*\+\s*&(?P<base>{IDENT})\s*,\s*(?P<object>{IDENT})\s*\)\s*;'
)


def variants(source, name, header, rows):
    if not 25 <= len(rows) <= 50:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.search(target)
    if not witness:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if 'sll $s0, $s0, 4' not in candidate:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__)\b', part.clean):
        return []
    part.end = end
    hits = list(_SOURCE.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    if (hit['base'] != witness['base'] or hit['out'] != witness['out']
            or len(re.findall(rf'\b{re.escape(hit["offset"])}\b', part.body)) != 4
            or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(void\s*\*\s*{re.escape(hit["object"])}\s*,'
                             rf'\s*s32\s+{IDENT}\s*,\s*s32\s+{re.escape(hit["index"])}\s*\)\s*$',
                             part.clean[:part.opening])):
        return []
    for symbol in (hit['base'], hit['out']):
        if not re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(symbol)}\s*;', part.clean[:part.opening]):
            return []
    # The offset is pure and the parameter cannot be modified by the allocator.
    if re.search(rf'(?<![\w]){re.escape(hit["index"])}\s*(?:=|\+\+|--|[+*/-]=)', hit['middle']):
        return []
    start = part.opening + 1
    original = source[start + hit.start():start + hit.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    offset = f'({hit["index"]} * 0x184)'
    replacement = (hit['middle'] + f'*(s32 *) ((char *) &{hit["out"]} + {offset}) = {hit["allocator"]};\n'
                   f'    {hit["call"]}({offset} + (char *) &{hit["base"]}, {hit["object"]});')
    fixed = edit(source, [(start + hit.start(), start + hit.end(), replacement)])
    return [('measured_record_byte_offset', fixed)]
