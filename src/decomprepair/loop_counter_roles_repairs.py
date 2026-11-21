"""Which loops share a counter variable, varied: one loop's own counter, two counters merged, a loop moved to another.

GCC 2.x hands the saved registers to the pseudos that live across calls in the order of
floor_log2(uses) * uses / live length, each use counting one more for every loop it sits in. A counter variable is
one pseudo for the whole function, so the loops that share `var_s1` give one register to all of them, and which of
two counters outranks the other depends on how many loops, uses and instructions each one spans. m2c names a few
variables for the registers a binary used and shares them between loops; the game's own code had its own pairing,
and the pairing decides which counter lands in which saved register. A counter's instructions are the same either
way, so this changes only what the allocator sees.

A counter loop here is a local integer `v` set by a plain `v = <number>;` just before a `do { } while`, `for`,
`while` or `label: ... if (c) goto label;` loop, stepped in its body and tested in its condition. Its *region* runs
from that set to the end of the loop. Every mention of `v` in the function must lie in one of its regions, so no
value ever flows from one loop's counter into another's (each region sets before it reads); anything else, a
counter read after its loop or whose address is taken, is left alone. Three operations, each one a rename:

- `loop_counter_fresh`: one loop of a variable shared by several gets a new variable of the same type;
- `loop_counter_reassign`: one loop takes another counter variable of the same type whose own regions don't
  overlap it (the loop's region may not contain another region of that variable);
- `loop_counter_merge`: two variables of one type whose regions never overlap become one;
- `loop_counter_swap`: two loops trade their variables.

Singles come before pairs and the number is capped. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .loop_address_hoist_repairs import _loops, _match

LIMIT = 24
INTEGER = (r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|[su](?:8|16|32)|u?int(?:8|16|32)_t')
IDENT = r'[A-Za-z_]\w*'
BETWEEN = 4  # at most this many plain statements may sit between a counter's set and its loop
FRESH, REASSIGN, MERGE, SWAP = 'loop_counter_fresh', 'loop_counter_reassign', 'loop_counter_merge', 'loop_counter_swap'


def _mentions(clean, var, start, end):
    return [(start+m.start(), start+m.end()) for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', clean[start:end])]


def _condition(clean, loop):
    """The text of the loop's own test, or None when its shape isn't one this reads."""
    start, end = loop
    text = clean[start:end]
    if re.match(r'(?:for|while)\b', text):
        paren = text.find('(')
        close = _match(text, paren, '(', ')') if paren >= 0 else -1
        return text[paren:close+1] if close > 0 else None
    if re.match(r'do\b', text):
        hit = re.search(r'while\s*(\([^;{}]*\))\s*;\s*$', text)
        return hit[1] if hit else None
    label = re.match(rf'({IDENT})\s*:', text)
    if label:
        hit = re.search(rf'if\s*(\([^;{{}}]*\))\s*\{{?\s*goto\s+{label[1]}\s*;\s*\}}?\s*$', text)
        return hit[1] if hit else None
    return None


def _stepped(clean, var, loop):
    v = re.escape(var)
    return bool(re.search(rf'(?<![\w.>]){v}\s*(?:\+\+|--|[+-]=\s*\w+)|(?:\+\+|--)\s*{v}\b|(?<![\w.>]){v}\s*=\s*{v}\s*[+-]', clean[loop[0]:loop[1]]))


def _set_before(clean, var, loop, floor):
    """Where the plain `var = number;` that starts this loop's region is, or None: the last one above the loop with
    no mention of `var`, jump or loop between it and the loop and at most BETWEEN statements."""
    window = clean[max(floor, loop[0]-600):loop[0]]
    base = max(floor, loop[0]-600)
    best = None
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(var)}\s*=\s*(?:-?\d+|0x[0-9A-Fa-f]+)\s*;', window):
        best = hit
    if best is None:
        return None
    between = window[best.end():]
    if re.search(rf'(?<![\w.>]){re.escape(var)}\b', between) or between.count(';') > BETWEEN:
        return None
    if re.search(r'\b(?:goto|return|break|continue|case|default|do|for|while|if|else|switch)\b|^[ \t]*[A-Za-z_]\w*[ \t]*:(?!:)',
                 between, re.M):
        return None
    return base+best.start()


def _counters(source, name):
    """({var: (type, (decl start, decl end), [(region start, region end, [mention spans])])}, clean, body span)."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or re.search(r'\b(?:asm|__asm__)\b', clean[start:end]):
        return None
    loops = _loops(clean, opening, end)
    found = {}
    for decl in re.finditer(rf'(?m)^[ \t]*({INTEGER})[ \t]+({IDENT})[ \t]*;[ \t]*\n', clean[opening:end]):
        var = decl[2]
        if var in found or re.search(rf'(?<![\w.>])&\s*{var}\b', clean[opening:end]):
            continue
        spans = (opening+decl.start(), opening+decl.end())
        regions = []
        for loop in loops:
            cond = _condition(clean, loop)
            if cond is None or not re.search(rf'(?<![\w.>]){re.escape(var)}\b', cond) or not _stepped(clean, var, loop):
                continue
            first = _set_before(clean, var, loop, spans[1])
            if first is not None:
                regions.append((first, loop[1]))
        regions.sort()
        if not regions or any(a[1] > b[0] for a, b in zip(regions, regions[1:])):
            continue  # a loop inside another loop's region would have to share its counter
        every = [m for m in _mentions(clean, var, opening, end) if not spans[0] <= m[0] < spans[1]]
        owned = [[m for m in every if r[0] <= m[0] < r[1]] for r in regions]
        if sum(len(o) for o in owned) != len(every):
            continue  # a mention outside every counter loop: a value may flow, so the variable stays as it is
        found[var] = (' '.join(decl[1].split()), spans, [(r[0], r[1], o) for r, o in zip(regions, owned)])
    return found, clean, (opening, end)


def _fresh_name(clean, var, taken):
    for letter in 'bcdefghijklmnopqrstuvwxyz':
        candidate = f'{var}_{letter}'
        if candidate not in taken and not re.search(rf'\b{candidate}\b', clean):
            taken.add(candidate)
            return candidate
    return None


def _apply(source, edits):
    for start, stop, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        source = source[:start]+text+source[stop:]
    return source


def _rename(region, new):
    return [(a, b, new) for a, b in region[2]]


def _overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def variants(source, name):
    """Variants of function `name` that change which loops share a counter variable."""
    got = _counters(source, name)
    if not got or not got[0]:
        return []
    found, clean, _ = got
    regions = {var: info[2] for var, info in found.items()}
    result = []

    def add(label, edits):
        text = _apply(source, edits)
        if text != source and (label, text) not in result:
            result.append((label, text))

    taken = set()
    for var, (kind, decl, spans) in found.items():  # one loop of a shared counter takes a variable of its own
        if len(spans) < 2:
            continue
        for index in range(len(spans)):
            new = _fresh_name(clean, var, set(taken))
            if new is None:
                continue
            line = re.match(r'[ \t]*', clean[decl[0]:]).group()
            add(FRESH, [(decl[1], decl[1], f'{line}{kind} {new};\n'), *_rename(spans[index], new)])
    same = [(u, w) for u in found for w in found if u != w and found[u][0] == found[w][0]]
    for u, w in same:  # one loop of `u` counts with `w` instead, when w's own loops don't overlap it
        for region in regions[u]:
            if not any(_overlap(region, other) for other in regions[w]):
                add(REASSIGN, _rename(region, w))
    for u, w in same:
        if u < w and not any(_overlap(a, b) for a in regions[u] for b in regions[w]):
            add(MERGE, [*(e for r in regions[w] for e in _rename(r, u)), (found[w][1][0], found[w][1][1], '')])
    for u, w in same:  # two loops trade their counters
        if u < w:
            for a in regions[u]:
                for b in regions[w]:
                    if (not any(_overlap(a, o) for o in regions[w] if o is not b)
                            and not any(_overlap(b, o) for o in regions[u] if o is not a)):
                        add(SWAP, [*_rename(a, w), *_rename(b, u)])
    order = {FRESH: 0, REASSIGN: 1, MERGE: 2, SWAP: 3}
    result.sort(key=lambda item: order[item[0]])  # (stable: singles before pairs)
    return result[:LIMIT]
