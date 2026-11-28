"""A constant that only happens to equal an earlier one, stored through a local of its own.

    glyphs[40].y = 8;                  glyphs[40].y = 8;
    ...                          ->    ...
    glyphs[47].x = 8;                  wide_8 = 8;
                                       glyphs[47].x = wide_8;

SN GCC 2.8.1 (`-G0 -mips3 -O2 -mfp64`) keeps one register for a halfword constant that a straight-line run stores more
than once: a table initialiser whose rows all store `y = 8` and whose last entry stores `x = 8` reuses that register for
the `x`. The target loads the 8 again, in a register of its own, so the two were different values in the source: one that
reached the compiler through an `int` variable is another machine mode, which cse does not share with the halfword
constant (a hypothesis from the outputs; the compiler's source is not available). On a 301-instruction N64 font table
set-up this one edit was 595 -> 120 in the app, every register row of the last two entries.

The sign of a coincidence is a literal first stored into one member after the same literal was stored only into other
members, so one child is offered per such store: the rarest (value, member) pairs first, and among those the value
the run had stored most often elsewhere (the register most worth keeping apart).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'coincident_constant_local'
FAMILIES = (FAMILY,)
LIMIT = 24

STORE = re.compile(r'(?P<head>[ \t]*[^=;{}?]*?(?:\.|->)(?P<member>[A-Za-z_]\w*)[ \t]*=[ \t]*)'
                   r'(?P<value>-?(?:0[xX][0-9A-Fa-f]+|[1-9]\d*))(?P<tail>[ \t]*;[ \t]*)$')
# A line that ends the straight-line run: cse's constants do not reach past it.
BREAK = re.compile(r'[{}]|\breturn\b|\bgoto\b|^[ \t]*(?:case\b[^:]*|default|[A-Za-z_]\w*)[ \t]*:(?!:)')


def _runs(cleaned, lines, first, last):
    run = []
    for index in range(first + 1, last):
        if BREAK.search(cleaned[index]):
            yield run
            run = []
            continue
        if STORE.match(cleaned[index]):
            hit = STORE.match(lines[index])
            if hit:
                run.append((index, hit))
    yield run


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    lines = source.split('\n')
    cleaned = clean.split('\n')
    first, last = source.count('\n', 0, opening), source.count('\n', 0, end - 1)
    found = []
    for run in _runs(cleaned, lines, first, last):
        count = {}
        for _, hit in run:
            key = int(hit['value'], 0), hit['member']
            count[key] = count.get(key, 0) + 1
        members, seen, stored = {}, set(), {}
        for index, hit in run:
            value, member = int(hit['value'], 0), hit['member']
            earlier = members.setdefault(value, set())
            if earlier and member not in earlier and (value, member) not in seen:
                found.append((count[value, member], -stored[value], index, hit))
            seen.add((value, member))
            earlier.add(member)
            stored[value] = stored.get(value, 0) + 1
    result = []
    for _, _, index, hit in sorted(found, key=lambda item: item[:3])[:LIMIT]:
        value = int(hit['value'], 0)
        local = f'wide_{"m" if value < 0 else ""}{abs(value):x}'
        if re.search(r'\b' + local + r'\b', source):
            continue
        indent = re.match(r'[ \t]*', lines[index])[0]
        edited = list(lines)
        edited[index] = f'{indent}{local} = {hit["value"]};\n{hit["head"]}{local}{hit["tail"]}'
        edited[first] = lines[first] + f'\n  s32 {local};'
        result.append((FAMILY, '\n'.join(edited)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
