"""Constants an arm assigns after its calls, assigned at the head of the arm: they are then live across those calls.

m2c writes a variable's constant at the point of the last use before the join, after the arm's calls:

    if (border) { t = spawn(a); spawn(b); x = 0x18; y = 0x12; d = 3; ... } else { m = mark(); init(m); x = 0x24; ... }
    use(x, y, d);

A value assigned after the arm's last call is live only across code with no call in it, so global.c takes it a caller-saved
register (the allocation of a pseudo that does not cross a call: first free register already used by the function). The
game's constants were set at the head of each arm, before the calls, which makes the three values cross them and take
saved registers `$s1 $s2 $s5` like the target's; in a 795-instruction N64 object spawner that moved three values out of
`$a2 $a3 $a0` and the function's 8-byte frame hole closed with them (5195 -> 4665 with the other rows unchanged). The
reading of global.c is a hypothesis; the judge decides.

The shape: a braced arm of an `if`/`else` chain that calls a function before a statement `name = <integer literal>;`
where `name` is a local that nothing before that statement mentions and whose address is never taken. One child moves all
such statements of one arm to the head of the arm; with several arms, one more child moves them in every arm at once (the
three values of a join are one change: moving only one arm's leaves the other pair of definitions apart).
"""
import re

from .arm_block_support import (
    IDENT,
    KEYWORDS,
    NUMBER,
    brace_pairs,
    indentation,
    line_start,
    local_declaration,
    mentions,
    statements,
)
from .integer_repair_support import edit, view

FAMILY = 'arm_constants_to_head'
FAMILIES = (FAMILY,)

CONSTANT = re.compile(rf'(?P<name>{IDENT})\s*=\s*(?P<value>-?\s*{NUMBER})\s*;')
CALL = re.compile(rf'(?<![\w.>])({IDENT})\s*\(')


def _arms(clean, pairs):
    """The braced arms (`{` of an `if (...)` or an `else`) as (open, close), in source order."""
    arms = []
    for opening, closing in sorted(pairs.items()):
        before = clean[:opening].rstrip()
        if before.endswith('else'):
            arms.append((opening, closing))
        elif before.endswith(')'):
            depth, at = 0, len(before)
            while at > 0:
                at -= 1
                depth += (before[at] == ')') - (before[at] == '(')
                if depth == 0:
                    break
            if re.search(r'\bif$', clean[:at].rstrip()):
                arms.append((opening, closing))
    return arms


def _moves(source, clean, part, arm):
    """(statements to move as (start, end), head position) for one arm; empty when nothing qualifies."""
    opening, closing = arm
    units = statements(clean, opening + 1, closing)
    called = False
    moved = []
    for index, (start, end) in enumerate(units):
        text = clean[start:end]
        if called:
            hit = CONSTANT.fullmatch(text.strip())
            earlier = ' '.join(clean[a:b] for a, b in units[:index])
            name = hit['name'] if hit else None
            if (hit and local_declaration(clean, part.opening, name) and not mentions(earlier, name)
                    and not re.search(rf'&\s*{re.escape(name)}\b', clean[part.opening:part.end])
                    and name not in {clean[a:b].split('=')[0].strip() for a, b in moved}):
                moved.append((start, end))
                continue
        if any(m[1] not in KEYWORDS for m in CALL.finditer(text)):
            called = True
    return moved, units


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    plans = []
    for arm in _arms(clean, pairs):
        moved, units = _moves(source, clean, part, arm)
        if not moved or not units:
            continue
        # each arm must still begin with the statements that came first: only the statements move
        head = units[0][0]
        plans.append((arm, moved, head))
    out = []

    def plan_edits(plan):
        arm, moved, head = plan
        indent = indentation(clean, head) or '  '
        text = ''.join(source[a:b].strip() and indent + source[a:b].strip() + '\n' for a, b in moved)
        edits = [(line_start(clean, head), line_start(clean, head), text)]
        for a, b in moved:
            end = b
            while end < len(clean) and clean[end] in ' \t':
                end += 1
            if end < len(clean) and clean[end] == '\n':
                end += 1
            edits.append((line_start(clean, a) if not clean[line_start(clean, a):a].strip() else a, end, ''))
        return edits

    for plan in plans:
        text = edit(source, plan_edits(plan))
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    if len(plans) > 1:
        text = edit(source, [e for plan in plans for e in plan_edits(plan)])
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)
