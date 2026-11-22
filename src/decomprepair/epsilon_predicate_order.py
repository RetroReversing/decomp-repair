"""Swap the inverted integer predicates materialized from a float tolerance test."""

import re
import struct
from collections import Counter, defaultdict

from .balanced_float_predicate_return import _bits
from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions
from .operand_lifetime_repairs import _escaped, _in_scope, _typed_locals, _visible

FAMILY = 'epsilon_predicate_order'
STAGED = 'staged_epsilon_predicate_order'
FAMILIES = (FAMILY, STAGED)
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


_STAGED = re.compile(
    rf'(?m)^[ \t]*(?P<first>{IDENT})\s*=\s*1\s*;\s*'
    rf'if\s*\(!\((?P<value>{IDENT})\s*<=\s*(?P<limit>{_EPSILON})\)\)\s*'
    rf'\{{\s*(?P=first)\s*=\s*(?:\(unsigned\s+int\)\s*)?0\s*;\s*\}}\s*'
    rf'(?P<held>{IDENT})\s*=\s*(?P=first)\s*\^\s*1\s*;\s*'
    rf'(?P<second>{IDENT})\s*=\s*1\s*;\s*'
    rf'if\s*\(!\((?P=value)\s*>=\s*\(-(?P=limit)\)\)\)\s*'
    r'\{\s*(?P=second)\s*=\s*0\s*;\s*\}\s*'
    r'if\s*\(\s*\(\s*(?P<left>\(\s*(?P=second)\s*\^\s*1\s*\))\s*\|\s*'
    r'(?P<right>(?P=held))\s*\)\s*[!=]=\s*0\s*\)'
)
_COMPARE = re.compile(r'c\.le\.s (\$f\d+), (\$f\d+)')
_REVERSED = 'or $v0, $v0, $v1'


def _staged_sites(rows):
    targets = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    counts = Counter()
    for i in range(14, len(targets)):
        index, op = targets[i]
        if not _TARGET[2].fullmatch(op) or rows[index][2] != _REVERSED:
            continue
        prior = targets[i - 3:i]
        if not (_TARGET[0].fullmatch(prior[0][1]) and prior[1][1] == 'move $v0, $zero'
                and _TARGET[1].fullmatch(prior[2][1])
                and all(rows[position][2] == line for position, line in prior)):
            continue
        after, comparison = targets[i - 7]
        low = _COMPARE.fullmatch(comparison)
        if not low or rows[after][2] != comparison:
            continue
        lower = _bits(targets, i - 7, low[1])
        if not lower or not lower & 0x80000000:
            continue
        for j in range(i - 12, max(3, i - 27), -1):
            before, line = targets[j]
            high = _COMPARE.fullmatch(line)
            if not high or high[1] != low[2] or rows[before][2] != line:
                continue
            if _bits(targets, j, high[2]) == lower ^ 0x80000000:
                counts[lower ^ 0x80000000] += 1
                break
    return counts


def staged_variants(source, name, rows, *, header=''):
    """Reverse only the final operands after both integer inversions already match."""
    counts = _staged_sites(rows)
    visible = _visible(source, name, header) if counts else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\b(?:s32|u32)\s*;', context):
        return []
    locals_ = _typed_locals(part, r'(?:s32|u32|unsigned\s+int|int)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    choices = defaultdict(list)
    for hit in _STAGED.finditer(part.clean, part.opening + 1, part.end):
        flags = (hit['first'], hit['second'], hit['held'])
        if len(set(flags)) != 3 or macros & set(re.findall(IDENT, hit[0])):
            continue
        if any(flag not in locals_ or not _in_scope(part, locals_[flag][1], hit.start())
               or _escaped(part.body, flag) for flag in flags):
            continue
        try:
            bits = struct.unpack('>I', struct.pack('>f', float(hit['limit'][:-1])))[0]
        except OverflowError:
            continue
        if bits in counts:
            choices[bits].append([(*hit.span('left'), hit['right']), (*hit.span('right'), hit['left'])])
    changes = [change for bits, groups in choices.items() if len(groups) == counts[bits]
               for pair in groups for change in pair]
    return [(STAGED, edit(source, changes))] if changes else []
