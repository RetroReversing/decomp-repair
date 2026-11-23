"""A `break` that m2c put inside a `do { } while (0);` fence, meant for the `switch` around it.

m2c writes a block it jumps out of as `do { ...; break; } while (0);`, and in C that `break` leaves the fence, not the
switch arm: the statements after the fence run, which the target's `j tail` (straight to the arm's end) does not do. A
switch arm of a 970-instruction N64 state-machine handler (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) had a call
written `do { do { var = 8; call(var); break; } while (0); } while (0);` followed by the arm's next test; with the
fences gone the `break` leaves the switch, the tail merges with the other arms' calls and the test after it is no
longer reached from the call: 3390 -> 3120 for the two arms of that kind (1905 -> 1605 for the last).

`variants` takes each `do { ... } while (0);` fence whose own statements (not an inner loop's or switch's) include a
`break;`, and writes its body in its place together with every fence around it that holds nothing else. One child per
such fence, one with all of them, at most 6. A candidate rewrite: the exact judge decides whether the arm may skip the
statements after the fence.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines, loops

FAMILY = 'fence_break_unwrap'
FAMILIES = (FAMILY,)
LIMIT = 6
OPENERS = re.compile(r'(?:do|for|while|switch)\b')


def _fence(body, loop):
    do, opening, closing, whilst = loop
    return re.fullmatch(r'while\s*\(\s*0\s*\)\s*;', body[whilst].stripped) is not None


def _has_own_break(body, opening, closing):
    index = opening + 1
    while index < closing:
        text = body[index].stripped
        if OPENERS.match(text):
            nxt = index + 1
            inner = block_end(body, nxt) if nxt < closing and body[nxt].stripped == '{' else None
            if inner is None:
                index += 1
                continue
            index = inner + 1
            if text.startswith('do') and index < closing and body[index].stripped.startswith('while'):
                index += 1
            continue
        if text == 'break;':
            return True
        index += 1
    return False


def _only_child(body, outer, inner):
    """Whether the fence `outer` holds nothing but the fence `inner`."""
    do, opening, closing, whilst = outer
    return opening + 1 == inner[0] and inner[3] + 1 == closing


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    fences = [loop for loop in loops(body) if _fence(body, loop)]
    chains = []
    for loop in fences:
        if not _has_own_break(body, loop[1], loop[2]):
            continue
        chain = [loop]
        while True:
            parent = next((p for p in fences if p[0] < chain[-1][0] and chain[-1][3] < p[3] and _only_child(body, p, chain[-1])), None)
            if parent is None:
                break
            chain.append(parent)
        chains.append(chain)

    def edits(chain):
        found = []
        for do, opening, closing, whilst in chain:
            for index in (do, opening, closing, whilst):
                found.append((body[index].start, body[index].end, ''))
        return found

    out = []
    for chain in chains[:LIMIT]:
        child = apply(source, edits(chain))
        if child != source and child not in out:
            out.append(child)
    if len(chains) > 1:
        every = {}
        for chain in chains:
            for edit in edits(chain):
                every[edit[:2]] = edit
        child = apply(source, sorted(every.values()))
        if child not in out:
            out.append(child)
    return [(FAMILY, child) for child in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
