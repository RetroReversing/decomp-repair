"""Constants stored to many globals in a row: where the held constant's stores sit decides its register.

A straight run of `global = literal;` stores (a reset block, a table of defaults) is one scheduling block. GCC 2.7
(`gcc-2.7.2-kmc`, MIPS) loads each literal once and shares the register between its stores (cse), so a literal stored
twice is a pseudo that lives from its first store to its last. Hypothesis (not confirmed in local-alloc.c): a
literal used once is a short pseudo that the allocator puts in the first free temporary (`$v0`), so the repeated
literal only lands in another register (the target's `$a0`) when a one-shot temporary is stored *between* its first
and last store, and the second scheduler then gathers the one-shot temporaries at the top of the block while every
other store keeps its source order. One N64 function (a 145-instruction defaults reset, 210 as m2c wrote it) was
exact once

  * the first of two stores of one literal to the same global was dropped (cse only deletes it when the two stores
    are adjacent; with other stores between, both are emitted, one extra `lui/sb` pair), and
  * three one-shot stores (`0xEF`, `0x40`, `0x10`, in the target's order) were moved from the top of the run to
    sit between the repeated literal's remaining stores.

Neither half helps alone (dropping the duplicate alone: 1350; moving the three alone: 210 -> 1320), so the child
that does both is offered too. This never compiles or judges: the caller scores each candidate. Only runs whose
statements are all `global = literal;` are touched, so no call, read, local or aliasing store is reordered, and a
dropped store is one that a later store to the same global overwrites with nothing reading it in between.
"""
import itertools
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .paired_statement_moves import _analysis, _declared, _render

FAMILY = 'constant_store_bracket'
DROP_FAMILY = 'duplicate_constant_store_drop'
FAMILIES = (FAMILY, DROP_FAMILY)
LIMIT = 160
STORE = re.compile(rf'({IDENT})\s*=\s*({NUMBER}|{IDENT})\s*;')


def _value(text):
    """A literal's number, or the name of a local that holds a constant (a `u8 reset = 0xFF;` stored many times)."""
    return text if re.fullmatch(IDENT, text) else int(re.sub(r'[uUlL]+$', '', text), 0)


def _window(source, run, locals_):
    """Every maximal block of plain constant stores to globals in the run, each as (index in run, symbol, value)."""
    blocks, current = [], []
    for at, stmt in enumerate(run):
        hit = STORE.fullmatch(source[stmt.start:stmt.end].strip())
        if (hit and not stmt.unknown and not stmt.calls and not stmt.writes_local and stmt.global_writes == {hit[1]}
                and hit[1] not in locals_ and (not re.fullmatch(IDENT, hit[2]) or hit[2] in locals_)):
            current.append((at, hit[1], _value(hit[2])))
        else:
            if len(current) > 1:
                blocks.append(current)
            current = []
    if len(current) > 1:
        blocks.append(current)
    return blocks


def _dropped(block):
    """Indexes (in the run) of stores a later store of the same literal to the same global overwrites. Nothing in a
    block of constant stores reads memory, so only the symbol has to match."""
    seen, drops = {}, []
    for at, symbol, value in block:
        if symbol in seen and seen[symbol][1] == value:
            drops.append(seen[symbol][0])
        seen[symbol] = (at, value)
    return drops


def _splice(source, run, order):
    start, end, text = _render(source, run, order)
    return edit(source, [(start, end, text)])


def _brackets(block, dropped):
    """(order of the run's indexes) candidates, one per way to move a group of one-shot stores inside a repeated
    literal's span, with the stores in `dropped` removed first."""
    kept = [entry for entry in block if entry[0] not in dropped]
    counts = {}
    for _, _, value in kept:
        counts[value] = counts.get(value, 0) + 1
    orders = []
    shots = [e for e in kept if isinstance(e[2], int) and e[2] and counts[e[2]] == 1]
    for value in sorted(v for v, n in counts.items() if isinstance(v, int) and v and n > 1):
        places = [i for i, e in enumerate(kept) if e[2] == value]
        first, last = places[0], places[-1]
        for size in range(1, min(len(shots), 5) + 1):
            for group in (tuple(shots[i:i + size]) for i in range(len(shots) - size + 1)):
                if any(first < kept.index(e) < last for e in group):
                    continue  # already inside the span
                # keep the group's own order first, the other orders of a small group after
                variants = [group] if size > 3 else list(itertools.permutations(group))
                variants.sort(key=lambda g: g != group)
                for ordered in variants:
                    rest = [e for e in kept if e not in group]
                    where = [rest.index(kept[first]) + 1]
                    if last - first > 1:
                        where.append(rest.index(kept[last]))
                    for index in dict.fromkeys(where):
                        order = rest[:index] + list(ordered) + rest[index:]
                        orders.append([e[0] for e in order])
    return orders


def _block_children(source, run, block):
    """(family, source) for one block of constant stores: the chain (drop, then bracket) first, then each part."""
    first = block[0][0]
    outside = [at for at in range(len(run)) if at not in {e[0] for e in block}]
    prefix, suffix = outside[:first], outside[first:]
    drops = _dropped(block)
    children = []
    if drops:  # the whole chain first: drop the overwritten stores, then bracket
        children += [(FAMILY, _splice(source, run, prefix + order + suffix)) for order in _brackets(block, set(drops))]
    for gone in drops:
        children.append((DROP_FAMILY, _splice(source, run, [at for at in range(len(run)) if at != gone])))
    children += [(FAMILY, _splice(source, run, prefix + order + suffix)) for order in _brackets(block, set())]
    return children


def variants(source, name, header=''):
    runs = _analysis(source, name, header)
    part = view(source, name)
    locals_ = _declared(part.clean, part) if part else set()
    found, seen = [], {source}
    for run in runs or ():
        for block in _window(source, run, locals_):
            for family, text in _block_children(source, run, block):
                if text not in seen and len(found) < LIMIT:
                    seen.add(text)
                    found.append((family, text))
    return found
