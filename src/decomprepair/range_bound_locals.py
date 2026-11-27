"""Both bounds of a range test in narrow locals of their own, set before the `if`.

`if ((s16) (w + 0xC000) < x && x < (s16) (0x4000 - w))` -> `s16 low; s16 high; low = w + 0xC000; high = 0x4000 - w;
if (low < x && x < high)`. The written condition computes the second bound only after the first test's branch. As two
locals, both are computed in the block before it, so the scheduler can load the second bound's constant early and the
delay slot of the first branch can take its subtraction; the narrowing stays at the compare. The register and
scheduling explanation is a hypothesis; the measurement is one 81-instruction SN64 GCC 2.8.1 function, 540 -> 60 from
its saved best. One bound alone was worse there (735), so only the pair is offered, one `if` at a time.

Only bounds that are a narrowing cast of a call-free, assignment-free expression, compared with the same operand."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('range_bound_locals',)
LIMIT = 4
IF = re.compile(r'(?<=[;{}])\s*(?P<if>if)\s*\(')
CAST = re.compile(r'\(\s*(?P<type>[su](?:8|16))\s*\)\s*')
RELATION = re.compile(r'<<|>>|->|(?P<op><=|>=|<|>)')
IMPURE = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b(?!(?:M2C_FIELD)\b){IDENT}\s*\(|[?,]')


def _strip(text, start, end):
    """The span without surrounding blanks and without parentheses that enclose all of it."""
    while True:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end and text[start] == '(' and close(text, start, '(', ')') in (end, end - 1) \
                and text[end - 1] == ')':
            start, end = start + 1, end - 1
            continue
        return start, end


def _top(text, start, end, pattern):
    """The matches of `pattern` in the span that no parenthesis or bracket encloses."""
    found, depth, at = [], 0, start
    for hit in pattern.finditer(text, start, end):
        depth += sum(text[i] in '([' for i in range(at, hit.start())) - sum(text[i] in ')]' for i in range(at, hit.start()))
        at = hit.start()
        if depth == 0:
            found.append(hit)
    return found


def _bound(source, clean, start, end):
    """(type, expression text) when the operand is a narrowing cast of a pure expression."""
    start, end = _strip(clean, start, end)
    cast = CAST.match(clean, start, end)
    if not cast:
        return None
    inner_start, inner_end = cast.end(), end
    if inner_start >= end:
        return None
    if clean[inner_start] == '(':
        if close(clean, inner_start, '(', ')') not in (end, end - 1) or clean[end - 1] != ')':
            return None
        inner_start, inner_end = _strip(clean, inner_start, end)
    elif not re.fullmatch(IDENT, clean[inner_start:end].strip()):
        return None
    inner = clean[inner_start:inner_end]
    if IMPURE.search(inner):
        return None
    return cast['type'], source[inner_start:inner_end].strip()


def _term(source, clean, start, end):
    """[(operator span, cast bound or None, plain text, span of the bound side)] for both sides of one comparison."""
    start, end = _strip(clean, start, end)
    relations = [hit for hit in _top(clean, start, end, RELATION) if hit['op']]
    if len(relations) != 1:
        return None
    hit = relations[0]
    sides = [(start, hit.start()), (hit.end(), end)]
    out = []
    for number, (a, b) in enumerate(sides):
        other = sides[1 - number]
        bound = _bound(source, clean, a, b)
        if bound:
            shared = ''.join(clean[slice(*_strip(clean, *other))].split())
            at = a + len(clean[a:b]) - len(clean[a:b].lstrip())
            out.append((bound, shared, (at, a + len(clean[a:b].rstrip()))))
    return out or None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    clean, out = part.clean, []
    for found in IF.finditer(clean, part.opening, part.end):
        opening = found.end() - 1
        closing = close(clean, opening, '(', ')')
        if not closing:
            continue
        if clean[closing - 1] != ')':
            closing += 1
        start, end = opening + 1, closing - 1
        joins = _top(clean, start, end, re.compile(r'&&|\|\|'))
        if len(joins) != 1:
            continue
        first = _term(source, clean, start, joins[0].start())
        second = _term(source, clean, joins[0].end(), end)
        if not first or not second:
            continue
        pair = next(((a, b) for a in first for b in second if a[1] == b[1]), None)
        if not pair:
            continue
        names = []
        for word in ('range_low', 'range_high'):
            number, candidate = 1, word
            while re.search(rf'\b{candidate}\b', source):
                number += 1
                candidate = f'{word}_{number}'
            names.append(candidate)
        line = source.rfind('\n', 0, found.start('if')) + 1
        indent = re.match(r'[ \t]*', source[line:found.start('if')])[0]
        before = ''.join(f'{local} = {bound[1]};\n{indent}' for local, (bound, _, _) in zip(names, pair))
        declared = ''.join(f'\n    {bound[0]} {local};' for local, (bound, _, _) in zip(names, pair))
        edits = [(part.opening + 1, part.opening + 1, declared),
                 (found.start('if'), found.start('if'), before)]
        edits += [(span[0], span[1], local) for local, (_, _, span) in zip(names, pair)]
        text = edit(source, edits)
        out.append((FAMILIES[0], text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)
