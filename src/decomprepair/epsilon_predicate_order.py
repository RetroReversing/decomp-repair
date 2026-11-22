"""Swap the inverted integer predicates materialized from a float tolerance test."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions

FAMILY = 'epsilon_predicate_order'
FAMILIES = (FAMILY,)
_FLAG1 = r'var_v1(?:_\d+)?'
_FLAG0 = r'var_v0(?:_\d+)?'
_EPSILON = r'\d+\.\d+[fF]'
_PAIR = re.compile(
    rf'\b(?P<first>{_FLAG1})\s*=\s*1\s*;\s*'
    rf'if\s*\(\s*!\s*\(\s*(?P<value>{IDENT})\s*<=\s*(?P<limit>{_EPSILON})\s*\)\s*\)\s*'
    r'{\s*(?P=first)\s*=\s*0\s*;\s*}\s*'
    rf'(?P<second>{_FLAG0})\s*=\s*1\s*;\s*'
    r'if\s*\(\s*!\s*\(\s*(?P=value)\s*>=\s*\(\s*-\s*(?P=limit)\s*\)\s*\)\s*\)\s*'
    r'{\s*(?P=second)\s*=\s*0\s*;\s*}\s*'
    r'if\s*\(\s*\(\s*\(\s*(?P<left>(?P=first))\s*\^\s*1\s*\)\s*\|'
    r'\s*\(\s*(?P<right>(?P=second))\s*\^\s*1\s*\)\s*\)\s*[!=]=\s*0\s*\)')
_TARGET = (re.compile(r'xori\s+\$v1,\s*\$v1,\s*(?:1|0x1)'),
           re.compile(r'xori\s+\$v0,\s*\$v0,\s*(?:1|0x1)'),
           re.compile(r'or\s+\$v0,\s*\$v1,\s*\$v0'))


def _target_sites(rows):
    count = 0
    for i, op in enumerate(rows):
        if not _TARGET[2].fullmatch(op):
            continue
        preceding = rows[max(0, i-4):i]
        if (len(preceding) >= 2 and _TARGET[1].fullmatch(preceding[-1])
                and any(_TARGET[0].fullmatch(row) for row in preceding[:-1])
                and sum(row.startswith('c.le.s ') for row in rows[max(0, i-30):i]) >= 2):
            count += 1
    return count


def variants(source, name, asm):
    part = view(source, name) if asm and 'xori' in asm and 'c.le.s' in asm else None
    if not part:
        return []
    target_count = _target_sites(instructions(asm))
    choices = []
    for hit in _PAIR.finditer(part.clean, part.opening+1, part.end):
        if any(len(re.findall(rf'(?m)^[ \t]*(?:s32|u32|unsigned\s+int|int)\s+{hit[key]}\s*;', part.body)) != 1
               or re.search(rf'&\s*\(*\s*{hit[key]}\b', part.body) for key in ('first', 'second')):
            continue
        choices.append([(*hit.span('left'), hit['right']), (*hit.span('right'), hit['left'])])
    if not choices or len(choices) > target_count:
        return []
    proposals = choices[:4]
    if len(choices) > 1:
        proposals = [[change for group in choices for change in group], *proposals]
    return [(FAMILY, edit(source, changes)) for changes in proposals]
