"""Recover a measured inverted entry test and indexed-pointer operand order."""

import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'slti \$(?P<condition>\w+), \$(?P<index>\w+), 2\n'
    r'xori \$(?P=condition), \$(?P=condition), 1\nbeqz \$(?P=condition), [^\n]+\n'
    r'move \$\w+, \$zero\nsll \$(?P<scaled>\w+), \$(?P=index), 2\n'
    r'addu \$\w+, \$(?P=scaled), \$(?P<base>\w+)'
)
_SOURCE = re.compile(
    rf'if\s*\(\s*(?P<index>{IDENT})\s*>=\s*2\s*\)\s*{{\s*'
    rf'(?P<dst>{IDENT})\s*=\s*\(\s*(?P=index)\s*\*\s*4\s*\)\s*\+\s*(?P<base>{IDENT})\s*;'
)


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 80:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.search(target)
    if not witness:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if not re.search(rf'slti \${witness["condition"]}, \${witness["index"]}, 2\n'
                     rf'bnez \${witness["condition"]}, ', candidate):
        return []
    if not re.search(rf'addu \$\w+, \${witness["base"]}, \${witness["scaled"]}', candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_guard)\b', part.clean):
        return []
    part.end = end
    hits = list(_SOURCE.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    if len({hit['index'], hit['dst'], hit['base']}) != 3:
        return []
    declarations = locals_for(part)
    if not any(d['name'] == hit['index'] and d['type'] == 's32' for d in declarations):
        return []
    sig = part.clean[:part.opening]
    if not re.search(rf'\bvoid\s*\*\s*{re.escape(hit["base"])}\s*\)', sig):
        return []
    start = part.opening + 1
    original = source[start + hit.start():start + hit.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    condition = f'__repair_guard = ({hit["index"]} < 2) ^ 1;\n    if (__repair_guard) {{'
    address = (f'{hit["dst"]} = (void *) ((u32) ({hit["index"]} * 4)'
               f' + (u32) {hit["base"]});')
    replacement = condition + '\n        ' + address
    fixed = edit(source, [(start, start, '\n    s32 __repair_guard;'),
                          (start + hit.start(), start + hit.end(), replacement)])
    return [('measured_guarded_index', fixed)]
