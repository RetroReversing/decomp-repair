"""`size *= 8;` written back into its variable, versus the scale left at each use (an N64 heap setup, KMC GCC 2.7.2).

m2c writes a scaled value into the variable it scaled (`size *= 8;`), and every later read sees the product. When that
product is the argument of a call and is read again in an expression loop.c hoists (`buf + size`), the read that kills
the pseudo is the hoisted add: global.c then copies the call argument's preference (`$a0`) onto the sum, which ranks
below the loop's pointers and takes `$a0` away from them, so every pointer and counter below it moves one register
(28 register rows, score 140, with only the registers wrong). The original kept the unscaled value and scaled at each
use (`heapAlloc(size * 8, 0)` ... `buf + size * 8`): cse shares the product, the sum is a fresh pseudo with no
preference, and the registers fell into place (140 -> 0).

`scaled_size_inline` removes the `x *= K;` (or `x <<= n;`, `x = x * K;`) statement and writes `(x * K)` at every
later read of `x`, when nothing assigns `x`, takes its address or reads it before it is scaled again. A candidate
rewrite, not a proof: the exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'scaled_size_inline'
FAMILIES = (FAMILY,)
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'


def _statement(name):
    return re.compile(
        rf'(?m)^[ \t]*{name}\s*(?:\*=\s*(?P<mul>{NUMBER})|<<=\s*(?P<shift>{NUMBER})'
        rf'|=\s*{name}\s*\*\s*(?P<mul2>{NUMBER})|=\s*{name}\s*<<\s*(?P<shift2>{NUMBER}))\s*;[ \t]*\n')


def variants(source, name, limit=4):
    part = view(source, name)
    if not part:
        return []
    clean, base = part.clean, part.opening + 1
    body = clean[base:part.end - 1]
    result = []
    for local in dict.fromkeys(re.findall(r'(?m)^[ \t]*(?:[su](?:8|16|32)|int|unsigned(?:\s+int)?)\s+(\w+)\s*;', body)):
        hits = list(_statement(local).finditer(body))
        if len(hits) != 1:
            continue
        hit = hits[0]
        # a scale at the top level of the function: its line starts at the body's own indentation
        depth = body[:hit.start()].count('{') - body[:hit.start()].count('}')
        if depth:
            continue
        factor = hit['mul'] or hit['mul2']
        shift = hit['shift'] or hit['shift2']
        text = f'{local} * {factor}' if factor else f'{local} << {shift}'
        if factor and int(factor, 0) < 2 or shift and int(shift, 0) < 1:
            continue
        rest = body[hit.end():]
        reads = list(re.finditer(rf'(?<![\w.>]){local}\b', rest))
        if len(reads) < 2 or re.search(
                rf'(?<![*\w]){local}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\b{local}\s*(?:\+\+|--)|(?:\+\+|--)\s*{local}\b|&\s*{local}\b', rest):
            continue
        # the product feeds a call argument and a later expression, the shape that moves the registers
        if not re.search(rf'\w\s*\([^;]*(?<![\w.>]){local}\b', rest):
            continue
        edits = [(base + hit.start(), base + hit.end(), '')]
        edits += [(base + hit.end() + r.start(), base + hit.end() + r.end(), f'({text})') for r in reads]
        result.append((FAMILY, edit(source, edits)))
        # the same, with a 16-bit cast around a sum of the scaled value dropped: the cast was a way to give the sum
        # its own pseudo (and its `andi`), which the preference fix makes unnecessary
        for cast in re.finditer(rf'\((?:unsigned short|u16)\)\s*\(([^;()]*(?<![\w.>]){local}\b[^;()]*)\)', rest):
            start = base + hit.end() + cast.start()
            kept = [e for e in edits if not start <= e[0] < base + hit.end() + cast.end()]
            kept.append((start, base + hit.end() + cast.end(), '(' + re.sub(
                rf'(?<![\w.>]){local}\b', f'({text})', cast[1]) + ')'))
            result.append((FAMILY, edit(source, kept)))
    return result[:limit]
