"""Recover a halfword comparison following a masked word test on MIPS."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

# The two reads use the same address. This is a target-led correction of the
# draft's guessed field width, not a general replacement for a narrowing cast:
# on big-endian MIPS the halfword at that address is the word's high half.
_TARGET = re.compile(
    r'lw \$(?P<word>\w+), (?P<offset>\d+)\(\$(?P<base>\w+)\)\n'
    r'and \$\w+, \$(?P=word), \$\w+\nbeq \$\w+, \$\w+, [^\n]+\n'
    r'addiu \$a0, \$(?P=base), \d+\nlhu \$\w+, (?P=offset)\(\$(?P=base)\)\n'
    r'beq \$\w+, \$\w+, [^\n]+\nnop\n'
)
_DRAFT = re.compile(
    rf'\(\s*\(\s*M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)'
    rf'\s*&\s*{NUMBER}\s*\)\s*==\s*{NUMBER}\s*\)\s*\|\|\s*'
    rf'\(\s*(?P<cast>\(\s*u16\s*\)\s*M2C_FIELD\(\s*(?P=base)\s*,\s*s32\s*\*\s*,'
    rf'\s*(?P<again>{NUMBER})\s*\))\s*!=\s*{NUMBER}\s*\)'
)


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 80:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.search(target)
    candidate = normalized_integer_lines(right for _, _, right in rows if right)
    if not observed or not any(re.fullmatch(r'andi \$\w+, \$\w+, 65535', line) for line in candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\bvolatile\b', part.clean):
        return []
    part.end = end
    matches = list(_DRAFT.finditer(part.body))
    if len(matches) != 1:
        return []
    hit = matches[0]
    offset = integer(hit['offset'])
    if offset != integer(hit['again']) or offset != int(observed['offset']):
        return []
    start = part.opening + 1
    original = source[start + hit.start():start + hit.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    replacement = f'M2C_FIELD({hit["base"]}, u16 *, {hit["again"]})'
    fixed = edit(source, [(start + hit.start('cast'), start + hit.end('cast'), replacement)])
    return [('measured_masked_halfword_read', fixed)]
