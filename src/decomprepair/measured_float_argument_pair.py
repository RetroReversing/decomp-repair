"""Recover two leading float arguments from their measured MIPS registers."""

import re

from .csource import _blank, find
from .float_bit_argument_repairs import INTEGER_PARAMETER, LITERAL, TYPE_WORDS, _prototypes, float_text
from .integer_repair_support import IDENT, edit, split_args
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$at, (?P<first>\d+)\nmtc1 \$at, \$f12\n'
    rf'lui \$at, (?P<second>\d+)\nmtc1 \$at, \$f14\n'
    rf'lui \$a2, [^\n]+\njal (?P<callee>{IDENT})\n'
)


def variants(source, name, header, rows):
    if not 15 <= len(rows) <= 80:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = list(_TARGET.finditer(target))
    if len(observed) != 1:
        return []
    hit = observed[0]
    bits = [int(hit['first']) << 16, int(hit['second']) << 16]
    values = [float_text(value) for value in bits]
    if None in values:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if not all(re.search(rf'lui \${register}, {value}\b', candidate)
               for register, value in zip(('a0', 'a1'), (hit['first'], hit['second']))):
        return []
    clean = _blank(source)
    span = find(source, name)
    if not span or hit['callee'] == name or re.search(r'\b' + re.escape(hit['callee']) + r'\s*\(', _blank(header)):
        return []
    if re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    prototype = _prototypes(clean, span).get(hit['callee'])
    if not prototype:
        return []
    low, high = prototype
    params = [(low + a, low + b) for a, b in split_args(clean[low:high])]
    if len(params) != 3 or not all(INTEGER_PARAMETER.fullmatch(clean[a:b]) for a, b in params[:2]):
        return []
    opening = clean.find('{', span[0], span[1])
    calls = list(re.finditer(r'(?<![\w.>])' + re.escape(hit['callee']) + r'\s*\(', clean[opening:span[1]]))
    if len(calls) != 1:
        return []
    start = opening + calls[0].end() - 1
    end = close(clean, start)
    if not end:
        return []
    args = [(start + 1 + a, start + 1 + b) for a, b in split_args(clean[start + 1:end - 1])]
    if len(args) != 3:
        return []
    changes = []
    for index, (a, b) in enumerate(args[:2]):
        literal = LITERAL.fullmatch(clean[a:b])
        if not literal or int(literal[1], 0) != bits[index] or source[a:b] != clean[a:b]:
            return []
        changes.append((a, b, ' ' + values[index] if clean[a:a + 1] == ' ' else values[index]))
    for a, b in params[:2]:
        if source[a:b] != clean[a:b]:
            return []
        # Keep a parameter name, if the source prototype has one.
        words = clean[a:b].strip().split()
        param = 'f32' + (' ' + words[-1] if len(words) > 1 and words[-1] not in TYPE_WORDS else '')
        changes.append((a, b, (' ' if clean[a:a + 1] == ' ' else '') + param))
    return [('measured_float_argument_pair', edit(source, changes))]
