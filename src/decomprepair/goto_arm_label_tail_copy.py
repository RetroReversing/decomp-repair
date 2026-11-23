"""A labelled arm that falls out of its `if` into a `goto`, copied in place of each `goto` into it, with that `goto` after it.

`goto_arm_label_copy` copies a labelled run that ends in a jump. m2c's shared arm often ends by falling out of the `if`
that holds it, onto the `goto join;` that follows the whole `if`/`else`:

    if (!(flip == 1)) { shared: h = 0x78; } else { w = 0xA0; }
    goto join;
    ...                       (an outside path)    w = 0xA0; goto shared;

The compiler lays the arm out once and the outside path jumps into the middle of the `if`; the target has the assignment on
both paths (`bnel` over a copy of it in its delay slot, `j` to the join with the other assignment in its slot). A KMC
GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) player-update routine of 1137 instructions went 745 -> 570 with the copy placed
before the preceding assignment and 320 -> 60 in the order after it (with the arm polarity and the stores, one hill-climb
step); the two orders are offered. Hypothesis from the match: a jump into the middle of an arm makes the arm a join point,
which blocks the delay-slot fills the target has.

goto_arm_label_tail_copy
    A label at the head of a braced block that is the arm of an `if`, whose run (the block after the label) does not end in a
    jump, and whose whole `if`/`else` statement is followed directly by `goto M;`: every `goto label;` that is a statement of its
    own (after `;`, `{` or `}`) outside the run is replaced by the run and `goto M;`; one child places the copy right where
    the `goto` was, one places it before the statement just ahead of the `goto` when that is a plain assignment. The label
    stays when other `goto`s to it remain. At most 4 children."""
import re

from .goto_arm_label_copy import _BAD_RUN, _DECL, RUN_LIMIT
from .join_tail_arm_split_repairs import _blocks, _body, _gotos, _label
from .pattern_repairs import close, negate

FAMILY = 'goto_arm_label_tail_copy'
FAMILIES = (FAMILY,)
LIMIT = 6
_GOTO = re.compile(r'goto\s+([A-Za-z_]\w*)\s*;')
_PLAIN = re.compile(r'[^;{}()]*(?:\([^;{}()]*\))?[^;{}()]*=(?!=)[^;{}]*;')


def _parent(blocks, lo, hi):
    """(items, index of the statement holding the block that starts at lo) in the smallest enclosing block."""
    best = None
    for plo, phi, items in blocks:
        if (plo, phi) == (lo, hi) or not plo <= lo < hi <= phi:
            continue
        for index, (start, end) in enumerate(items):
            if start <= lo < end and (best is None or end - start < best[2]):
                best = (items, index, end - start)
    return best


def _swapped(source, clean, start, end):
    """(start, end, text) of the `if (C) {A} else {B}` at [start, end) written `if (!C) {B} else {A}` (or the plain
    negation of a single comparison), or None."""
    head = re.match(r'if\s*\(', clean[start:end])
    if not head:
        return None
    paren = start + head.end() - 1
    stop = close(clean, paren, '(', ')')
    opening = re.compile(r'\s*\{').match(clean, stop or 0)
    if not stop or not opening:
        return None
    a_open = opening.end() - 1
    a_end = close(clean, a_open, '{', '}')
    other = re.compile(r'(\s*)else(\s*)\{').match(clean, a_end or 0)
    if not a_end or not other:
        return None
    b_open = other.end() - 1
    b_end = close(clean, b_open, '{', '}')
    if not b_end or b_end > end:
        return None
    condition = source[paren + 1:stop - 1].strip()
    inner = re.fullmatch(r'!\s*\((.*)\)', condition, re.S)
    if inner and close(condition, condition.index('(')) == len(condition):
        negated = inner[1].strip()
    else:
        negated = negate(condition)
    if not negated:
        return None
    text = f'if ({negated})' + source[stop:a_open] + source[b_open:b_end] + other[1] + 'else' + other[2] + source[a_open:a_end]
    return start, b_end, text


def variants(source, name):
    part, end, clean = _body(source, name)
    if not part:
        return []
    blocks = _blocks(clean, part.opening + 1, end - 1)
    if not blocks:
        return []
    out = []
    for lo, hi, items in blocks[1:]:
        if len(items) < 2 or not (label := _label(clean, *items[0])):
            continue
        run = items[1:]
        text = clean[run[0][0]:run[-1][1]]
        if (len(run) > RUN_LIMIT or _BAD_RUN.search(text) or any(_DECL.match(clean[a:b]) for a, b in run)
                or re.match(r'(?:goto|return|break|continue)\b', clean[run[-1][0]:run[-1][1]])):
            continue
        parent = _parent(blocks, lo, hi)
        if not parent or parent[1] + 1 >= len(parent[0]):
            continue
        holder_items, index, _ = parent
        if not re.match(r'if\b', clean[holder_items[index][0]:holder_items[index][1]]):
            continue
        after = clean[holder_items[index + 1][0]:holder_items[index + 1][1]]
        join = _GOTO.fullmatch(after.strip())
        if not join or join[1] == label:
            continue
        run_text = source[run[0][0]:run[-1][1]]
        jumps = [m for m in _gotos(clean, part, label) if not run[0][0] <= part.opening + m.start() < run[-1][1]]
        built = []
        for order in ('after', 'before'):
            edits = []
            for jump in jumps:
                at, stop = part.opening + jump.start(), part.opening + jump.end()
                head = clean[:at].rstrip()
                if head[-1:] not in (';', '{', '}'):
                    continue
                line = source.rfind('\n', 0, at) + 1
                indent = re.match(r'[ \t]*', source[line:])[0]
                if order == 'after':
                    edits.append((at, stop, f'{run_text.strip()}\n{indent}goto {join[1]};'))
                else:
                    previous = head[max(head.rfind(';', 0, len(head) - 1), head.rfind('{'), head.rfind('}')) + 1:]
                    if not _PLAIN.fullmatch(previous.strip()):
                        continue
                    first = source.rfind('\n', 0, head.rfind(previous.strip())) + 1
                    edits.append((first, stop, f'{indent}{run_text.strip()}\n' + source[first:head.rfind(previous.strip()) + len(previous.strip())]
                                  + f'\n{indent}goto {join[1]};'))
            if not edits:
                continue
            child = source
            for start, stop, new in sorted(edits, reverse=True):
                child = child[:start] + new + child[stop:]
            built.append((FAMILY, child))
            flip = _swapped(source, clean, holder_items[index][0], holder_items[index][1])
            if flip and not any(flip[0] <= e[0] < flip[1] or e[0] <= flip[0] < e[1] for e in edits):
                both = source
                for start, stop, new in sorted(edits + [flip], reverse=True):
                    both = both[:start] + new + both[stop:]
                built.append((FAMILY, both))
        out += built
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
