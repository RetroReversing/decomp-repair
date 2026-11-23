"""A scratch local written into a dead local of the same type, the way the game reused one variable for unrelated values.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) voice-picker. Two spots in it gave a scratch value a
local of its own where the target reused the register of a variable the code had finished with:

  * the commit's two link bytes (`t = link->previous; if (t != 0xFF) ...; u = link->next; ...`) were read into locals
    of their own, which global.c ranks after the pointer and puts in `$a1`; the target has them in `$t0`, the register
    of the chain walk's `idx`, because the game used `idx` again (360 -> 330);
  * the product `off = idx * 0x1A0` of the last search loop was a variable of its own (`$v1`, with a spill copy `move
    $a1,$v1` after its first use) where the target holds it in the register of the loop's cursor copy, which is dead
    once the cursor has been read (455 -> 60, together with the register of the other temporaries of that loop).

dead_scratch_reuse
    A top-level local `X` whose every occurrence lies in one stretch of one block, the first of them an assignment
    in a block that encloses the rest, is renamed to another top-level local `Y` of the same type that does not
    occur in that stretch, is written before every read after it, and, when the stretch is in a loop, before every read
    in the loop body. `X` must not have its address taken. One child per `(X, Y)` with up to three `Y` per `X`, and
    one child per `Y` renaming every `X` that can take it when their stretches do not overlap. The declaration of `X`
    is dropped when it stands alone on its line. Hypothesis from the match, not from the compiler source: a name that
    stands for one more value of a variable gives global.c one pseudo with more references where the source gave it two,
    so the register order of both follows the shared one.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .guarded_loop_for import _written_before_read
from .integer_repair_support import DECL, edit, view

FAMILY = 'dead_scratch_reuse'
FAMILIES = (FAMILY,)
LIMIT = 12
PER_LOCAL = 3
_LOOP_HEADER = re.compile(r'^(?:for|while|do)\b')


def _occurrences(clean, name, low, high):
    """Absolute (start, end) of each use of `name` in clean[low:high] that is not a member of something."""
    return [(low + m.start(), low + m.end()) for m in re.finditer(rf'\b{re.escape(name)}\b', clean[low:high])
            if not re.search(r'(?:->|\.)\s*$', clean[low:low + m.start()])]


def _plan(source, clean, opening, end):
    """(name, type, [occurrence spans], declaration span or None) of every top-level plain integer local."""
    low = opening + 1
    out = []
    for decl in DECL.finditer(clean, low, end):
        if enclosing_block(clean, decl.start(), low) >= 0:
            continue
        out.append((decl['name'], re.sub(r'\s+', ' ', decl['type']), decl.span()))
    return out


def _valid(clean, low, high, x, y, first, last):
    """X's stretch [first, last) can hold Y: Y is absent from it and dead across it."""
    if _occurrences(clean, y, first, last):
        return False
    if not _written_before_read(clean, last, low, high, y):
        return False
    block = enclosing_block(clean, first, low)
    while block >= 0:
        if _LOOP_HEADER.match(header_before(clean, block)):
            stop = close(clean, block)
            if stop < 0 or not _written_before_read(clean, block + 1, block + 1, stop, y):
                return False
        block = enclosing_block(clean, block, low)
    return True


def _children(source, clean, opening, end):
    low = opening + 1
    locals_ = _plan(source, clean, opening, end)
    declared = {name: kind for name, kind, _ in locals_}
    spans = {name: span for name, _, span in locals_}
    found = []
    for x, kind, declaration in locals_:
        body = _occurrences(clean, x, declaration[1], end)
        if len(body) < 2 or re.search(rf'&\s*{re.escape(x)}\b', clean[low:end]):
            continue
        first, last = body[0][0], body[-1][1]
        if not re.match(rf'{re.escape(x)}\s*=(?!=)', clean[first:]):
            continue
        owner = enclosing_block(clean, first, low)
        owner_close = close(clean, owner) if owner >= 0 else end
        if owner_close < last:
            continue
        candidates = []
        for y, other in declared.items():
            if y == x or other != kind or not _valid(clean, low, end, x, y, first, last):
                continue
            before = [stop for _, stop in _occurrences(clean, y, low, first)]
            candidates.append((first - max(before) if before else len(clean), y))
        # the variable that went dead most recently first: its register is the one the game reused
        for _, y in sorted(candidates)[:PER_LOCAL]:
            found.append((x, y, body, (first, last)))
    return found, spans


def _drop(source, span):
    start, stop = span
    first = source.rfind('\n', 0, start) + 1
    last = source.find('\n', stop)
    if not source[first:start].strip() and last >= 0 and not source[stop:last].strip():
        return first, last + 1, ''
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    found, spans = _children(source, part.clean, part.opening, part.end)
    found = sorted(found, key=lambda item: item[3][1] - item[3][0])[:LIMIT]  # a short stretch first (a scratch value)

    def edits(items):
        changes = [(a, b, y) for x, y, body, _ in items for a, b in body]
        for x, _, _, _ in items:
            dropped = _drop(source, spans[x])
            if dropped:
                changes.append(dropped)
        return edit(source, changes)

    children = [(FAMILY, edits([item])) for item in found]
    for y in dict.fromkeys(item[1] for item in found):
        group, taken = [], []
        for item in found:
            if item[1] != y or any(not (item[3][1] <= a or b <= item[3][0]) for a, b in taken) \
                    or any(item[0] == other[0] for other in group):
                continue
            group.append(item)
            taken.append(item[3])
        if len(group) > 1:
            children.append((FAMILY, edits(group)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
