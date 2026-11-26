"""A nest of overwritten defaults written back as the `else if` ladder it came from.

m2c writes `if (a) x = K0; else if (b) x = K1; else x = y;` as a default that the next level overwrites: `x = K0;
if (!(a)) { x = K1; if (!(b)) { x = y; } }`. The two compile differently. With the default assigned before its test the
value lives across the test, so it takes another register than the loaded value it is compared with, and the compiler
may keep that load for the later tests. Written as the ladder, a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O1`)
three-level clamp of a signed byte loaded the byte again for each test into the result's own register, as the target
did: 640 -> 0 in one step on a 29-instruction N64 function (no scaffolding).

Unlike ladder_result_narrow (a ladder of constants whose result a call reads), the last level may be any expression,
the result may be used anywhere and the tests need not be negations. The move keeps the program's meaning when every
value but the last is a constant and no test mentions the result, which is all the family accepts. Needs two tests or
more (one default before one `if` is default_else_repairs' shape).
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close, negate

FAMILY = 'default_nest_ladder'
FAMILIES = (FAMILY,)
LIMIT = 4
_CONSTANT = re.compile(rf'\(?\s*-?\s*(?:{NUMBER})\s*\)?')


def _skip(clean, at):
    while at < len(clean) and clean[at].isspace():
        at += 1
    return at


def _assign(clean, at, var):
    """`var = EXPR;` at `at`: ((start, end) of EXPR, position after the `;`) or None."""
    hit = re.compile(rf'{re.escape(var)}\s*=(?!=)\s*').match(clean, at)
    if not hit:
        return None
    stop = clean.find(';', hit.end())
    if stop < 0 or re.search(r'[{}]', clean[hit.end():stop]):
        return None
    return (hit.end(), stop), stop + 1


def _level(clean, start, end, var):
    """clean[start:end] as `var = K; if (c) { LEVEL }` or `var = EXPR;`: ([(test span, value span)], value span)."""
    first = _assign(clean, _skip(clean, start), var)
    if not first:
        return None
    value, at = first
    if re.search(rf'(?<![\w.>]){re.escape(var)}\b', clean[value[0]:value[1]]):
        return None
    at = _skip(clean, at)
    if at >= end:
        return [], value
    test = _test(clean, at, var)
    if not test or _skip(clean, test[2]) < end or not _CONSTANT.fullmatch(clean[value[0]:value[1]].strip()):
        return None
    below = _level(clean, test[1] + 1, test[2] - 1, var)
    if not below:
        return None
    return [(test[0], value)] + below[0], below[1]


def _test(clean, at, var):
    """`if (c) { ... }` with no `else` at `at`: ((start, end) of c, position of `{`, position after `}`) or None."""
    hit = re.compile(r'if\s*\(').match(clean, at)
    if not hit:
        return None
    shut = close(clean, hit.end() - 1)
    if not shut:
        return None
    where = (hit.end(), shut - 1)
    condition = clean[where[0]:where[1]]
    if re.search(rf'(?<![\w.>]){re.escape(var)}\b|\+\+|--|(?<![=!<>])=(?!=)', condition):
        return None
    brace = _skip(clean, shut)
    if clean[brace:brace + 1] != '{':
        return None
    done = close(clean, brace, '{', '}')
    if not done or clean.startswith('else', _skip(clean, done)):
        return None
    return where, brace, done


def _opposite(condition):
    """The test's negation, as a person would write it."""
    condition = condition.strip()
    if condition.startswith('!'):
        rest = condition[1:].strip()
        if rest.startswith('(') and close(rest, 0) == len(rest):
            return rest[1:-1].strip()
        if re.fullmatch(IDENT, rest):
            return rest
    while condition.startswith('(') and close(condition, 0) == len(condition):
        condition = condition[1:-1].strip()
    return negate(condition) or f'!({condition})'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*=(?!=)[^;{{}}]*;\s*if\s*\(', clean[part.opening:part.end]):
        var, start = hit[1], part.opening + hit.start()
        if clean[:start].rstrip()[-1:] not in ';{}':
            continue
        test = _test(clean, _skip(clean, clean.find(';', start) + 1), var)
        if not test:
            continue
        arms = _level(clean, start, test[2], var)
        if not arms or len(arms[0]) < 2 or any(a <= start < b for a, b, *_ in found):
            continue
        found.append((start, test[2], var, *arms))
    out = []
    for start, stop, var, arms, otherwise in found[:LIMIT]:
        line = source[source.rfind('\n', 0, start) + 1:start]
        indent = re.match(r'[ \t]*', line)[0]
        text = ''
        for at, ((a, b), (c, d)) in enumerate(arms):
            head = f'if ({_opposite(source[a:b])})'
            text += f'{head} {{\n{indent}    {var} = {source[c:d].strip()};\n{indent}}} else '
        c, d = otherwise
        text += f'{{\n{indent}    {var} = {source[c:d].strip()};\n{indent}}}'
        out.append((FAMILY, edit(source, [(start, stop, text)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
