"""The same two neighbouring assignments swapped in every block that repeats them.

A function that does one thing three times (a cubic's coefficients for x, y and z, written with scratch variables the
blocks share: `a = ...; b = ...; c = ...;`) has the same order in all three blocks, and the order is not neutral. With
the blocks' scratch variables shared, each is one multi-set pseudo and the order of its assignments is the order the
scheduler must keep (an anti-dependence cannot be crossed): `b` before `a` in all three blocks scored 12706 where `a`
before `b` was an exact match (a 163-instruction float function, KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`). A swap
in one block alone changes one of three pseudos' order and is worse than either whole order, so no one-block step finds
it: the whole-function swap is its own child.

For every pair of neighbouring one-line assignments `A = ...;` `B = ...;` to two different plain variables where neither
statement mentions the other's target and neither calls a function, the pair's names key a swap. `variants` offers, for
each key that occurs in at least two places, every occurrence swapped at once (`repeated_block_order_swap`), and each
single occurrence swapped (`repeated_block_order_swap_one`, capped). A candidate rewrite; the exact judge decides.
"""
import re

from .csource import _blank, find
from .line_scan import lines

FAMILY = 'repeated_block_order_swap'
ONE_FAMILY = 'repeated_block_order_swap_one'
FAMILIES = (FAMILY, ONE_FAMILY)
MAX_KEYS = 6
MAX_ONE = 6
IDENT = r'[A-Za-z_]\w*'
ASSIGN = re.compile(rf'^(?P<indent>[ \t]*)(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}]*);[ \t]*$')


def _mentions(text, name):
    return re.search(rf'(?<![\w.>]){re.escape(name)}\b', text) is not None


def _pairs(source, name):
    span = find(source, name)
    if not span:
        return None, []
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not head:
        return None, []

    class Part:
        opening = span[0] + head.end() - 1
        end = span[1]

    Part.clean = clean
    body = lines(Part, source)
    found = []
    for i in range(len(body) - 1):
        first, second = ASSIGN.match(body[i].text), ASSIGN.match(body[i + 1].text)
        if not first or not second or first['name'] == second['name']:
            continue
        if _mentions(second['value'], first['name']) or _mentions(first['value'], second['name']):
            continue
        if any(re.search(rf'{IDENT}\s*\(|\+\+|--', statement['value']) for statement in (first, second)):
            continue
        found.append((first['name'], second['name'], body[i], body[i + 1]))
    return source, found


def _swap(source, occurrences):
    for _, _, first, second in sorted(occurrences, key=lambda o: o[2].start, reverse=True):
        swapped = second.source + '\n' + first.source + '\n'
        source = source[:first.start] + swapped + source[second.end:]
    return source


def variants(source, name):
    source, found = _pairs(source, name)
    if not found:
        return []
    keys = {}
    for occurrence in found:
        keys.setdefault((occurrence[0], occurrence[1]), []).append(occurrence)
    out = []
    for _, occurrences in sorted(keys.items(), key=lambda item: (-len(item[1]), item[0]))[:MAX_KEYS]:
        if len(occurrences) > 1:
            text = _swap(source, occurrences)
            if text != source:
                out.append((FAMILY, text))
    for occurrence in found[:MAX_ONE]:
        text = _swap(source, [occurrence])
        if text != source:
            out.append((ONE_FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
