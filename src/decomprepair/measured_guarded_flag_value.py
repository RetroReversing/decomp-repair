"""Delay a local flag expression until its guarded use, as the target does."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'lbu \$v1, -(?P<offset>\d+)\(\$a1\)\naddiu \$v0, \$zero, (?P<test>\d+)\n'
    r'beq \$v1, \$v0, [^\n]+\nori \$v1, \$a0, (?P<mask>\d+)\nsw \$v1, \(\$a1\)'
)
_SOURCE = re.compile(
    rf'(?P<assignment>(?P<dst>{IDENT})\s*=\s*(?P<src>{IDENT})\s*\|\s*(?P<mask>{NUMBER})\s*;)\s*'
    rf'if\s*\(\s*M2C_FIELD\(\s*&(?P<global>{IDENT})\s*,\s*u8\s*\*\s*,\s*-(?P<offset>{NUMBER})\s*\)'
    rf'\s*!=\s*(?P<test>{NUMBER})\s*\)\s*{{'
)


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 45:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    witness = _TARGET.search(target)
    if not witness or not re.search(rf'ori \$a1, \$v0, {witness["mask"]}\nlbu \$v1, -{witness["offset"]}\(\$a0\)', candidate):
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
    if (hit['src'] == hit['dst'] or integer(hit['mask']) != int(witness['mask'])
            or integer(hit['offset']) != int(witness['offset']) or integer(hit['test']) != int(witness['test'])
            or f'%hi({hit["global"]})' not in target
            or not re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(hit["global"])}\s*;', part.clean[:part.opening])
            or not all(re.search(rf'\bs32\s+{re.escape(hit[key])}\s*;', part.body) for key in ('src', 'dst'))
            or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{re.escape(hit["src"])}|{re.escape(hit["dst"])})\b',
                         source + '\n' + header)):
        return []
    start = part.opening + 1
    brace = start + hit.end() - 1
    branch_end = close(part.clean, brace, '{', '}')
    if (not branch_end or re.search(rf'\b{re.escape(hit["dst"])}\b', part.clean[branch_end:part.end])
            or re.search(rf'&\s*{re.escape(hit["dst"])}\b', part.body)
            or len(re.findall(rf'\b{re.escape(hit["dst"])}\s*=(?!=)', part.body)) != 1):
        return []
    line = source.rfind('\n', 0, start + hit.start()) + 1
    if source[line:start + hit.start()].strip():
        return []
    original = source[start + hit.start():start + hit.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    changes = [(start + hit.start('assignment'), start + hit.end('assignment'), ''),
               (brace + 1, brace + 1, '\n        ' + hit['assignment'])]
    return [('measured_guarded_flag_value', edit(source, changes))]
