"""A weight ladder lowered: the one-shot scopes around one statement removed, or one fewer.

`local_weight_ladder` and `call_weight_ladder` wrap statements in `do { S } while (0);` several deep, because GCC 2.7.2
counts a reference once per loop depth (flow.c) and `global.c` hands out the saved registers by `floor_log2(uses) * uses
/ live_length` (hypothesis, from `-dl -dg` dumps). Nothing took a ladder down again: a wrapper added to lift one
variable over a neighbour also lifts every other value that statement names, so a later edit (here a `loop_goto_form`
on the call that reads them) found the over-weighted variable ranked one place too high, and no family proposed
lowering it. In a 94-instruction object-action function the target needed `var_s7 = *(s16 *)(...)` with no scope while
the rest of the ladder stayed (the exact source: 135 and 145 with either edit alone, 0 with both; docs/learnings).

For each statement wrapped by one chain of `do { ... } while (0);` scopes, the chain with every scope removed
(`ladder_trim`) and with one scope fewer (`ladder_trim_one`). Only chains around a single plain statement (no brace,
label, `break` or `continue`) are touched. The judge decides; the two edits that pay off together are found by a
chain's `--combine`, which needs each half offered by itself, and ranks children by their own score, so a half that
scores worse alone is never among the ones it merges: `ladder_trim_goto` offers the pair itself, one chain's scopes
removed together with one `loop_goto_form` child (the call's scope written as a backward `goto` that never runs)."""
import difflib
import re

from . import loop_goto_form_repairs
from .integer_repair_support import edit, view
from .pattern_repairs import close

FULL = 'ladder_trim'
ONE = 'ladder_trim_one'
PAIR = 'ladder_trim_goto'
FAMILIES = (FULL, ONE, PAIR)
LIMIT = 20
PAIR_LIMIT = 40
OPEN = re.compile(r'\bdo\s*\{')
TAIL = re.compile(r'\s*while\s*\(\s*0\s*\)\s*;')


def _wrapper(clean, at, end):
    """(open_brace, after_close_brace, tail_end) of the `do { } while (0);` that starts at `at`, or None."""
    hit = OPEN.match(clean, at, end)
    if not hit:
        return None
    opening = hit.end() - 1
    stop = close(clean, opening, '{', '}')
    tail = TAIL.match(clean, stop, end) if stop else None
    return (opening, stop, tail.end()) if tail else None


def _chains(part):
    """(start, end, depth, statement offsets) of each outermost chain of one-shot scopes round a single statement."""
    clean, found, at, end = part.clean, [], part.opening + 1, part.end - 1
    while at < end:
        hit = OPEN.search(clean, at, end)
        if not hit:
            break
        outer = _wrapper(clean, hit.start(), end)
        if not outer:
            at = hit.end()
            continue
        depth, inner_start, inner_end = 1, outer[0] + 1, outer[1] - 1
        while True:
            lead = clean[inner_start:inner_end]
            skip = len(lead) - len(lead.lstrip())
            nested = _wrapper(clean, inner_start + skip, inner_end)
            if nested and clean[nested[2]:inner_end].strip() == '':
                depth += 1
                inner_start, inner_end = nested[0] + 1, nested[1] - 1
                continue
            break
        body = clean[inner_start:inner_end]
        if body.count(';') == 1 and body.rstrip().endswith(';') and not re.search(r'[{}:]|\b(?:break|continue|goto|return)\b', body):
            found.append((hit.start(), outer[2], depth, (inner_start + len(body) - len(body.lstrip()),
                                                         inner_start + len(body.rstrip()))))
        at = outer[2]
    return found


def _merge(base, first, second):
    """`base` with the line edits of both children, or None when they touch the same lines."""
    lines = base.splitlines(keepends=True)
    changes = []
    for child in (first, second):
        rows = child.splitlines(keepends=True)
        ops = difflib.SequenceMatcher(None, lines, rows, autojunk=False).get_opcodes()
        changes += [(a, b, rows[c:d]) for tag, a, b, c, d in ops if tag != 'equal']
    changes.sort(key=lambda change: (change[0], change[1]))
    if any(later[0] < earlier[1] or later[0] == earlier[0] for earlier, later in zip(changes, changes[1:])):
        return None
    out, at = [], 0
    for a, b, replacement in changes:
        out += lines[at:a] + replacement
        at = b
    return ''.join(out + lines[at:])


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'^\s*#', part.body, re.M):
        return []
    result = []
    for start, stop, depth, (first, last) in _chains(part):
        statement = source[first:last]
        result.append((FULL, edit(source, [(start, stop, statement)])))
        if depth > 1:
            shallow = 'do { ' * (depth - 1) + statement + ' } while (0);' * (depth - 1)
            result.append((ONE, edit(source, [(start, stop, shallow)])))
    result = result[:LIMIT]
    gotos = [child for _, child in loop_goto_form_repairs.variants(source, name)]
    trims = [child for family, child in result if family == FULL]
    pairs = []
    for trim in trims:
        for goto in gotos:
            merged = _merge(source, trim, goto)
            if merged and merged != source:
                pairs.append((PAIR, merged))
    return result + pairs[:PAIR_LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
