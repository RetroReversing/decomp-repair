"""Stage an indexed byte-clear base before the loop as the target does."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'move \$a1, \$zero\nandi \$a0, \$a0, 255\n'
    rf'lui \$v1, %hi\((?P<table>{IDENT})\)\naddiu \$v1, \$v1, %lo\((?P=table)\)\n'
    rf'sll \$v0, \$a0, 3\nsubu \$v0, \$v0, \$a0\nsll \$v0, \$v0, 1\n'
    rf'addu \$v1, \$v0, \$v1\nandi \$v0, \$a1, 255\n'
    rf'addu \$v0, \$v1, \$v0\nsb \$zero, \(\$v0\)'
)
_SOURCE = re.compile(
    rf'(?P<init>(?P<index>{IDENT})\s*=\s*0\s*;)\s*'
    rf'do\s*{{\s*\*\(\(\(\s*(?P<arg>{IDENT})\s*&\s*0xFF\s*\)\s*\*\s*0x[Ee]\s*\)\s*'
    rf'\+\s*(?P<table>{IDENT})\s*\+\s*\(\s*(?P=index)\s*&\s*0xFF\s*\)\s*\)\s*=\s*0\s*;\s*'
    rf'(?P=index)\s*\+=\s*1\s*;\s*}}\s*while\s*\(\s*\(u32\)\s*\(\s*(?P=index)\s*&\s*0xFF\s*\)'
    rf'\s*<\s*0x[Ee]U\s*\)\s*;'
)


def variants(source, name, header, rows):
    if not 15 <= len(rows) <= 30:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.search(target)
    if not witness:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if not re.search(r'andi \$v0, \$v1, 255\naddu \$v0, \$a0, \$v0', candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_base)\b', part.clean):
        return []
    part.end = end
    hits = list(_SOURCE.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    if (hit['table'] != witness['table'] or hit['arg'] == hit['index']
            or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*s32\s+{re.escape(hit["arg"])}\s*\)\s*$',
                             part.clean[:part.opening])
            or len(re.findall(rf'\b{re.escape(hit["arg"])}\b', part.body)) != 1
            or not re.search(rf'\bs32\s+{re.escape(hit["index"])}\s*;', part.body)
            or not re.search(rf'\bextern\s+char\s+{re.escape(hit["table"])}\s*\[\s*\]\s*;', part.clean[:part.opening])):
        return []
    start = part.opening + 1
    original = source[start + hit.start():start + hit.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    setup = (hit['init'] + f'\n    {hit["arg"]} &= 0xFF;\n'
             f'    do {{ __repair_base = {hit["table"]}; __repair_base += {hit["arg"]} * 14; }} while (0);')
    replacement = re.sub(rf'\(\(\({re.escape(hit["arg"])}\s*&\s*0xFF\)\s*\*\s*0x[Ee]\)\s*'
                         rf'\+\s*{re.escape(hit["table"])}\s*\+\s*\({re.escape(hit["index"])}\s*&\s*0xFF\)\)',
                         f'(__repair_base + ({hit["index"]} & 0xFF))', original)
    if replacement == original:
        return []
    replacement = replacement.replace(hit['init'], setup, 1)
    fixed = edit(source, [(start, start, '\n    char *__repair_base;'),
                          (start + hit.start(), start + hit.end(), replacement)])
    return [('measured_byte_clear_base', fixed)]
