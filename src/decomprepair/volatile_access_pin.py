"""Two neighbouring accesses through one base pointer, both made `volatile`, so the scheduler keeps their source order.

sched.c orders two memory references only when it must: `read_dependence` and `true_dependence` return a dependence for
a pair whose references are both volatile (`MEM_VOLATILE_P (x) && MEM_VOLATILE_P (mem)`), and none for two plain
accesses at different offsets from the same base register (`memrefs_conflict_p` proves them disjoint). Two such
accesses, a store and the load after it or two loads, are therefore free to swap, and the scheduler's priorities and
its stable-sort tie-break (backward scheduling puts the later insn first when two are equally good) decide which
comes first. A target whose order is the source's order ("the mode half-word is stored, then the vector is read",
"the flag word is read, then the saved coordinate") was out of reach of every spelling of the plain code: statement
order, locals and types changed nothing, because the RTL was the same. Marking exactly those two accesses `volatile`
keeps them in order and nothing else moves: on a 603-instruction N64 state machine (KMC GCC 2.7.2) at 120, two pairs
did it, 120 -> 60 each and 0 together (a store of the mode and the load of the first coordinate; a load of a flag
word and the load of the first coordinate). The original's accesses were probably `volatile`-qualified hardware-style
fields; the compiler's own order is what is being asked for here.

A proposal marks two consecutive simple statements, in the same straight run of statements, that each hold exactly one
access `*((T *) (((char *) base) + off))` (or the compact spelling) to the same base at different offsets, at least
one of them a load. Labelled `volatile_access_pin`: each such pair alone, a store followed by a load first, up to a
limit; no other access is touched. Accesses already `volatile` are left alone.
"""
import re

from .csource import _blank, find

FAMILY = 'volatile_access_pin'
FAMILIES = (FAMILY,)
LIMIT = 24

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_TYPE = r'(?P<type>[A-Za-z_][\w ]*?)'
_ACCESS = re.compile(
    rf'\*\(\(\s*{_TYPE}\s*\*\s*\)\s*\(\(\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<base>{_ID})\s*\)\s*\+\s*(?P<off>{_NUM})\s*\)\)'
    rf'|\*\(\s*{_TYPE.replace("type", "ctype")}\s*\*\s*\)\s*\(\(\s*(?:char|u8|s8)\s*\*\s*\)\s*(?P<cbase>{_ID})\s*\+\s*(?P<coff>{_NUM})\s*\)')
_SKIP = re.compile(r'\s*(?:if|else|while|for|do|switch|case|default|return|goto|break|continue|typedef)\b')
_EFFECT = re.compile(r'\+\+|--|\w\s*\(')


def _statements(clean, opening, closing):
    """[(start, end, adjacent_to_previous)] of the simple statements `... ;` in the function body."""
    out, start, previous_end = [], opening + 1, None
    depth = 0
    for at in range(opening + 1, closing):
        ch = clean[at]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch in '{}:':
            start, previous_end = at + 1, None
        elif depth == 0 and ch == ';':
            text = clean[start:at]
            if text.strip() and not _SKIP.match(text):
                adjacent = previous_end is not None and not clean[previous_end:start].strip()
                out.append((start, at + 1, adjacent))
            start, previous_end = at + 1, at + 1
    return out


def _accesses(clean, begin, end):
    found = []
    for m in _ACCESS.finditer(clean, begin, end):
        kind = (m['type'] or m['ctype']).strip()
        base = m['base'] or m['cbase']
        offset = int(m['off'] or m['coff'], 0)
        found.append((m.start(), m.end(), kind, base, offset, bool(m['type'] is None)))
    return found


def _is_store(clean, begin, access_end):
    """True when the access is the target of an assignment (`*acc = ...` / `*acc |= ...`)."""
    return bool(re.match(r'\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', clean[access_end:access_end + 5]))


def _mark(source, access):
    at = access[0]
    after = re.compile(r'\*\(\(?\s*').match(source, at).end()
    return source[:after] + 'volatile ' + source[after:]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    statements = _statements(clean, opening, closing)
    pairs = []
    for (a, b, _), (c, d, adjacent) in zip(statements, statements[1:]):
        if not adjacent:
            continue
        first, second = _accesses(clean, a, b), _accesses(clean, c, d)
        if len(first) != 1 or len(second) != 1 or _EFFECT.search(clean[a:b].replace(clean[first[0][0]:first[0][1]], '')) \
                or _EFFECT.search(clean[c:d].replace(clean[second[0][0]:second[0][1]], '')):
            continue
        x, y = first[0], second[0]
        if x[3] != y[3] or x[4] == y[4] or re.search(r'\bvolatile\b', clean[x[0]:x[1]] + clean[y[0]:y[1]]):
            continue
        store_first = _is_store(clean, a, x[1])
        store_second = _is_store(clean, c, y[1])
        if store_first and store_second:
            continue
        pairs.append((not (store_first and not store_second), a, x, y))
    out, seen = [], set()
    for _, _, x, y in sorted(pairs, key=lambda item: (item[0], item[1])):
        # mark the later access first so the earlier offsets stay valid
        new = source
        for access in sorted((x, y), key=lambda item: -item[0]):
            new = _mark(new, access)
        if new != source and new not in seen:
            seen.add(new)
            out.append((FAMILY, new))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
