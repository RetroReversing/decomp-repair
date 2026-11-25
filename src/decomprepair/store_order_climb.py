"""A hill climb over the order of a long block of independent statements: a search strategy, not a rewrite.

`store_run_order` offers the single moves of a run (each adjacent swap, each statement to the front and to the back)
and `statement_group_orders` every order of a small group. A long block of independent stores (an object initialiser,
a packet or record writer of eight and more lines) has too many orders for a grid (8! = 40,320, and the diff of a
full grid says nothing), and a greedy descent over one move stalls where the intermediate orders tie. Hand work on SN
GCC 2.8.1 N64 initialisers found the way through: move ONE line at a time and keep the move when the score does
not get worse (a tie is kept too, so the climb walks the plateau): 118 such steps took one block from 45 to 0, and a
slower annealing over the same moves took another from 1085 to 50. The scoring is the caller's (it compiles and
judges), so the strategy is a function that takes the scorer:

    best, score, tried = climb(source, name, scorer, header='', budget=300)

`scorer(source)` returns the number to minimise (the diff's score; lower is better) or None when the candidate does not
compile. `climb` starts from `source`, and at each step walks the moves of every run of `MINIMUM` or more statements
(`store_run_order._moves`: only moves whose passed statements commute with the moved one, so the program is the same
program) in the order `store_run_order` ranks them, takes the first one that scores better than the current source,
and when no move does takes the first that ties (at most `PLATEAU` ties in a row, none revisited: a set of sources
seen stops cycles). It stops at a score of 0, when no move improves or ties, or after `budget` scorer calls, and
returns the best source seen, its score and the number of scorer calls. Nothing here compiles; the app's Deep
Permuter local lane wires `climb` to its own scorer (decompdecomp: `app/deep_permuter`), and every candidate is still
judged by the byte judge."""
import re

from .integer_repair_support import view
from .store_run_order import _moves, _names, _rebuild, _records, _segments

MINIMUM = 8
PLATEAU = 60
BUDGET = 300


def blocks(source, name, header='', minimum=MINIMUM):
    """The runs of `minimum` or more independent-statement candidates of the function, each as the group
    `store_run_order._segments` builds, or [] when the function cannot be read (volatile, asm, goto)."""
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean[part.opening:part.end]):
        return []
    names = _names(part, source)
    records = _records(header + '\n' + source)
    return [group for group in _segments(source, part, names, records) if len(group) >= minimum]


def moves(source, name, header='', minimum=MINIMUM):
    """Every single-line move of every long block, best-ranked first: [child source]."""
    ranked = []
    for number, group in enumerate(blocks(source, name, header, minimum)):
        for rank, distance, order in _moves(source, group):
            ranked.append((rank, distance, number, order, group))
    children = []
    for *_, order, group in sorted(ranked, key=lambda item: item[:3]):
        child = _rebuild(source, group, order)
        if child != source and child not in children:
            children.append(child)
    return children


def climb(source, name, scorer, header='', budget=BUDGET, minimum=MINIMUM, plateau=PLATEAU):
    """(best source, its score, scorer calls); the source unchanged with its own score when no move helps."""
    calls = 0

    def score(text):
        nonlocal calls
        calls += 1
        return scorer(text)

    current, current_score = source, score(source)
    best, best_score = current, current_score
    if current_score is None:
        return source, None, calls
    seen, ties = {source}, 0
    while current_score and calls < budget:
        fallback = None
        moved = False
        for child in moves(current, name, header, minimum):
            if child in seen:
                continue
            if calls >= budget:
                break
            seen.add(child)
            value = score(child)
            if value is None:
                continue
            if value < current_score:
                current, current_score, ties, moved = child, value, 0, True
                break
            if value == current_score and fallback is None:
                fallback = child
        if not moved:
            if fallback is None or ties >= plateau:
                break
            current, ties = fallback, ties + 1
        if current_score < best_score:
            best, best_score = current, current_score
    return best, best_score, calls
