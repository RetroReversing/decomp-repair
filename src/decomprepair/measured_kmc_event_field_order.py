"""Recover the measured order of disjoint event fields before an indirect call."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'addiu \$v0, \$zero, (?P<literal>\d+)\nsh \$v0, (?P<half>\d+)\(\$a2\)\n'
    r'andi \$v0, \$s2, 255\nsw \$v0, (?P<word>\d+)\(\$a2\)'
)
_SOURCE = re.compile(
    rf'(?P<word>M2C_FIELD\((?P<base>{IDENT}), s32 \*, (?P<wordoff>{NUMBER})\)\s*=\s*'
    rf'\(s32\)\s*\((?P<arg>{IDENT})\s*&\s*0xFF\)\s*;)\s*'
    rf'(?P<half>M2C_FIELD\((?P=base), s16 \*, (?P<halfoff>{NUMBER})\)\s*=\s*(?P<literal>{NUMBER})\s*;)'
)


def variants(source, name, header, rows):
    if not 30 <= len(rows) <= 45:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.search(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (not observed or ('andi $v0, $s2, 255', '') not in changes
            or (f'sw $v0, {observed["word"]}($a2)', '') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.search(part.body)
    if (not draft or integer(draft['wordoff']) != int(observed['word'])
            or integer(draft['halfoff']) != int(observed['half'])
            or integer(draft['literal']) != int(observed['literal'])
            or not re.search(rf'\bvoid {re.escape(name)}\(void \*{IDENT}, void \*{IDENT}, s32 {re.escape(draft["arg"])}\)\s*$',
                             part.clean[:part.opening])
            or re.search(r'\bvolatile\b', part.clean[part.opening:part.end])):
        return []
    word, half = integer(draft['wordoff']), integer(draft['halfoff'])
    if not (word + 4 <= half or half + 2 <= word):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + draft.start('word'), start + draft.end('word'), draft['half']),
                          (start + draft.start('half'), start + draft.end('half'), draft['word'])])
    return [('measured_disjoint_event_field_order', fixed)]
