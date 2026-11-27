"""m2c's nested `!=` ladder, written as the equality chain it came from, all levels at once.

A compiler lays `if (x == 0) {A} else if (x == 1) {B} else if (x == 2) {C}` out with the later arms' tests falling
through, and m2c reads it back inside out, often with the arms' common last store behind a label:

    if (x != 0) {
        if (x != 1) {
            if (x == 2) { v = *p + 16000; goto block; }
        } else { v = *p + 12000; goto block; }
    } else { v = *p + 8000; block: *p = v; }

Giving each `goto` its own copy of the tail (`goto_shared_tail`) judged no better on its own, and turning one level
around leaves the others inside out. The child here does both: every level whose `!=` arm is only the next test
becomes `if (x == K) <its else> else <the next test>`, after the tails are copied. A second child also writes each
arm's `p = address; *p = *p + k;` on the place (`arm_pointer_update_inline`). On an N64 score routine of 73
instructions (SN GCC 2.8.1, -O2) the two took the best of the library's chain to an exact match. Negating a test and
exchanging its arms keeps the program, whatever the test.
"""
import re

from . import arm_pointer_update_inline, goto_structure_repairs
from .csource import _blank, find
from .goto_structure_repairs import parse
from .pattern_repairs import close

FAMILY = 'inverted_guard_ladder'
FAMILIES = (FAMILY,)

_TEST = re.compile(r'\s*(?P<x>[A-Za-z_]\w*)\s*(?P<op>[!=])=\s*(?P<k>-?(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*)\s*\Z')


def _only_if(part):
    """The one `if` a block holds, or None."""
    return part['stmts'][0] if part and len(part['stmts']) == 1 and part['stmts'][0].kind == 'if' else None


def _arm(source, part):
    text = source[part['open']:part['close']].strip()
    return text if part['block'] else '{ ' + text + ' }'


def _column(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return len(line) - len(line.lstrip(' '))


def _ladder(source, stmt):
    """(chain text, levels turned around) for an `if` and the tests nested in it, or None when it is no ladder."""
    cond = source[slice(*stmt.parts['cond'])]
    test = _TEST.match(cond)
    if not test:
        return None
    then, other = stmt.parts['then'], stmt.parts.get('other')
    inner = _only_if(then)
    if test['op'] == '!' and other and inner is not None:
        rest = _ladder(source, inner)
        if rest and _TEST.match(source[slice(*inner.parts['cond'])])['x'] == test['x']:
            first = f'if ({test["x"]} == {test["k"]}) {_arm(source, other)}'
            extra = _column(source, inner.start) - _column(source, stmt.start)
            turned = re.sub(rf'\n {{{max(extra, 0)}}}', '\n', rest[0])
            return f'{first} else {turned}', rest[1] + 1
    return source[stmt.start:stmt.end].strip(), 0


def _statements(stmts):
    for stmt in stmts:
        yield stmt
        for key in ('then', 'other', 'body'):
            part = stmt.parts.get(key)
            if part:
                yield from _statements(part['stmts'])


def _flatten(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    try:
        statements = parse(clean, opening + 1, end - 1)
    except (ValueError, RecursionError):
        return None
    for stmt in _statements(statements):
        if stmt.kind != 'if':
            continue
        found = _ladder(source, stmt)
        if found and found[1]:
            return source[:stmt.start] + found[0] + source[stmt.end:]
    return None


def variants(source, name):
    starts = [source]
    if re.search(r'\bgoto\b', source):
        starts = [text for family, text in goto_structure_repairs.variants(source, name)
                  if family == 'goto_shared_tail'][:2] + starts
    for start in starts:
        flat = _flatten(start, name)
        if flat is None:
            continue
        children = [text for _, text in arm_pointer_update_inline.variants(flat, name)] + [flat]
        return [(FAMILY, text) for text in children]
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 500}
