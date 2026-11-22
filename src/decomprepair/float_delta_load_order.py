"""Capture a measured float difference's first field before its second field."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _in_scope, _typed_locals, _visible

FAMILY = 'float_delta_load_order'
FRESH = 'repair_delta_input'
REG = r'\$\w+'
_LOAD = re.compile(rf'lwc1 ({REG}), ({NUMBER})\(({REG})\)')
_SUB = re.compile(rf'sub\.s ({REG}), ({REG}), ({REG})')
_FIELD = re.compile(rf'\*\(\(f32\*\)\(\(\(char\*\)({IDENT})\)\+({NUMBER})\)\)')
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<low>{IDENT})\s*=\s*(?P<low_read>\*\([^;\n]+\));[ \t]*\n'
    rf'(?P=pad)(?P<delta>{IDENT})\s*=\s*\(\(\s*(?P<high_read>\*\([^;\n]+?\))\s*\)\s*'
    rf'-\s*(?P=low)\s*\)\s*\*\s*[-+]?\d+\.\d+[fF]\s*;'
)


def _targets(rows):
    order = set()
    for a, b, c in zip(rows, rows[1:], rows[2:]):
        if a[0] == b[0] == ' ':
            continue
        high, low, prior_low, prior_high = (_LOAD.fullmatch(line) for line in (a[1], b[1], a[2], b[2]))
        subtract = _SUB.fullmatch(c[1])
        if not all((high, low, prior_low, prior_high, subtract)) or c[1] != c[2]:
            continue
        if high.groups() != prior_high.groups() or low.groups() != prior_low.groups() or low[3] != high[3]:
            continue
        if subtract.group(2, 3) == (high[1], low[1]) and high[1] != low[1] and high[2] != low[2]:
            order.add((integer(high[2]), integer(low[2])))
    return order


def variants(source, name, rows, *, header=''):
    targets = _targets(rows)
    visible = _visible(source, name, header) if targets else None
    if not visible:
        return []
    part, context = visible
    if re.search(rf'\b{FRESH}\b|typedef[^;\n]*\bvolatile\b[^;\n]*\bf32\b', context):
        return []
    locals_ = _typed_locals(part, r'(?:f32|float)')
    edits = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        if m['low'] == m['delta'] or any(k not in locals_ or not _in_scope(part, locals_[k][1], m.start())
                                        for k in (m['low'], m['delta'])):
            continue
        high, low = (_FIELD.fullmatch(re.sub(r'\s+', '', m[group])) for group in ('high_read', 'low_read'))
        if not high or not low or high[1] != low[1] or (integer(high[2]), integer(low[2])) not in targets:
            continue
        before = part.clean[part.opening + 1:m.start()].rstrip()
        if (before and before[-1] not in ';{}:') or re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        names = '|'.join((high[1], m['low'], m['delta'], 'f32'))
        if re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{names})\b|'
                     rf'\b(?:volatile|_Atomic)\b[^;{{}}\n]*\b{high[1]}\b', context):
            continue
        read = source[slice(*m.span('high_read'))]
        edits.append([(part.opening + 1, part.opening + 1, f'\n    f32 {FRESH};'),
                      (m.start(), m.start(), f'{m["pad"]}{FRESH} = {read};\n'),
                      (*m.span('high_read'), FRESH)])
    return [(FAMILY, edit(source, edits[0]))] if len(edits) == 1 else []
