"""Recover a byte global's addressed branch update from MIPS instructions."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<global>{IDENT})\)\naddiu \$v1, \$v1, %lo\((?P=global)\)\n'
    r'lbu \$v0, \(\$v1\)\nsltiu \$v0, \$v0, (?P<limit>\d+)\nbeqz \$v0, [^\n]+\n'
    r'addiu \$v0, \$zero, (?P=limit)\nlbu \$v0, \(\$v1\)\n'
    r'addiu \$v0, \$v0, (?P<increment>\d+)\njr \$ra\nsb \$v0, \(\$v1\)'
)
_SOURCE = re.compile(
    rf'\s*u8\s+(?P<local>{IDENT})\s*;\s*(?P=local)\s*=\s*(?P<limit>{NUMBER})\s*;\s*'
    rf'if\s*\(\s*\(u8\)\s*(?P<global>{IDENT})\s*<\s*(?P<test>{NUMBER})[uU]?\s*\)\s*{{\s*'
    rf'(?P=local)\s*=\s*(?P=global)\s*\+\s*(?P<increment>{NUMBER})\s*;\s*}}\s*'
    rf'(?P=global)\s*=\s*(?P=local)\s*;\s*'
)


def variants(source, name, header, rows):
    if not 10 <= len(rows) <= 20:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.fullmatch(target)
    if not witness:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if (f'lui $v0, %hi({witness["global"]})' not in candidate
            or f'sb $v1, %lo({witness["global"]})($at)' not in candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_byte_ptr)\b', part.clean):
        return []
    part.end = end
    draft = _SOURCE.fullmatch(part.body)
    if (not draft or draft['global'] != witness['global']
            or integer(draft['limit']) != int(witness['limit'])
            or integer(draft['test']) != int(witness['limit'])
            or integer(draft['increment']) != int(witness['increment'])
            or not 0 < int(witness['limit']) <= 255
            or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\)\s*$', part.clean[:part.opening])
            or not re.search(rf'\bextern\s+u8\s+{re.escape(draft["global"])}\s*;', part.clean[:part.opening])):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    limit = draft['limit'].rstrip('uUlL')
    body = (f'\n    u8 *__repair_byte_ptr;\n    u8 {draft["local"]};\n\n'
            f'    __repair_byte_ptr = &{draft["global"]};\n'
            f'    if (*__repair_byte_ptr >= {limit}U) {{\n'
            f'        {draft["local"]} = {draft["limit"]};\n'
            f'    }} else {{\n        {draft["local"]} = *__repair_byte_ptr + {draft["increment"]};\n'
            f'    }}\n    *__repair_byte_ptr = {draft["local"]};\n')
    fixed = edit(source, [(part.opening + 1, part.end - 1, body)])
    return [('measured_byte_global_branch', fixed)]
