"""A join copy kept by a first reference above the join: the arm that skips it copies for itself, and the arms' flag
stores follow their guards (KMC GCC 2.7.2, `-O2`; the combination of three small edits that are each no better alone).

m2c writes the join of a switch as two labels in front of a copy and a test of the copy:

        ...  case 2: if (f(2, 0) == 3) { return; } goto check;
             case 4: force = 1; if (!ready) { return; } goto joined;
        joined:
        check:
        near = force;
        if (!near && !(dist(...) < limit)) { return; }

and the target keeps the copy (`move $v0,$s0; bnez $v0,..`, the flag in `$s0`, the copy's register `$v0`), with the arm
that came through `check` jumping past it with its own copy in the branch's slot, and the `j`s of the other arms left
unfilled (`j L; nop`). Three facts, each read in the compiler's source and reproduced with cc1's dumps:

1. cse deletes a copy whose destination is not live beyond the extended block and not referenced above it
   (`make_regs_eqv`: the new register becomes the quantity's canonical one only when its life reaches past the block or
   starts before it, otherwise the older register stays canonical, every use is rewritten to it and the copy dies). A
   copy written in the arm that jumps to `check` is a reference above the join, so `near` stays canonical and the copy
   at the join survives; the label `check` then belongs after the join's copy (`near = force; goto check;` in the arm,
   `check:` after the copy), which is also the program the target's layout reads as.
2. reorg (`fill_simple_delay_slots`, then `fill_eager_delay_slots` and `relax_delay_slots`, twice) fills each arm's `j` from
   the join's first insn and a guard's `beqz` steals the flag store from the `j` in front of it. Which `j` ends with a
   filled slot depends on where each arm's flag store sits relative to its guard, so the flag stores that m2c wrote
   before an early-`return` guard (`force = 1; if (!ready) { return; }`) have to follow it
   (`if (!ready) { return; } force = 1;`, the same program: the returning path never reads the local).
3. Neither edit reaches the target alone: the anchor alone leaves two `j`s with the join's copy in their slots (700 on
   a 250-instruction handler whose other 245 rows were right), the stores alone leave the copy folded away (1150), and
   the three together are exact (0). So the children below are the combination, not the parts.

Children: `join_copy_arm_anchor` (the anchor alone, so a function whose flag stores already follow their guards, or
whose slots the anchor alone fixes, reaches it in one step) and `join_copy_arm_anchor_sink` (the anchor with every flag
store of the arms that jump to the join moved after its guard).

The anchor is offered for two consecutive labels in front of a copy `d = s;` of two plain local integers when every
`goto` to the second label is a statement of its own; a flag store moves only when the guard is `if (c) { return; }`
(or `if (c) return;`) without an `else`, the condition does not read the flag, the flag is a local integer and the
statement is a plain assignment of a number. The rewrites keep the program's meaning (the copy is made once on every
path, and the flag is dead on the returning path); the compiler's explanation above is stated from its source, not
proved by a controlled experiment.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .pattern_repairs import close

FAMILY = 'join_copy_arm_anchor'
SINK_FAMILY = 'join_copy_arm_anchor_sink'
FAMILIES = (FAMILY, SINK_FAMILY)
LIMIT = 4
_KEYWORDS = {'case', 'default', 'return', 'else', 'goto', 'break', 'continue', 'switch', 'if', 'while', 'for', 'do'}
_JOIN = re.compile(rf'(?P<first>{IDENT})\s*:\s*(?P<second>{IDENT})\s*:\s*(?P<dst>{IDENT})\s*=\s*(?P<src>{IDENT})\s*;')
_FLAG = re.compile(rf'(?P<var>{IDENT})\s*=(?!=)\s*(?P<value>-?(?:0[xX][0-9a-fA-F]+|[0-9]+))\s*;')


def _locals(part):
    """The plain integer locals the function declares (`register` ones too; a `volatile` or global name is not one)."""
    head = part.clean[part.opening + 1:part.end]
    names = set()
    for hit in re.finditer(rf'(?:^|(?<=[;{{}}]))\s*(?:register\s+)?{INTEGER}\s+({IDENT})\s*;', head):
        names.add(hit[1])
    return names


def _standalone(clean, start):
    """True when the statement at `start` begins a statement of its own (not the body of an unbraced `if`)."""
    before = clean[:start].rstrip()
    return before[-1:] in ';{}:' and not re.search(r'\b(?:else|do)$', before)


def _gotos(part, label):
    return [hit for hit in re.finditer(rf'\bgoto\s+{re.escape(label)}\s*;', part.clean[part.opening + 1:part.end])]


def _anchor(source, part, hit, names):
    """The edits that give the arms their own copy and move the second label behind the join's."""
    first, second, dst, src = hit['first'], hit['second'], hit['dst'], hit['src']
    if first in _KEYWORDS or second in _KEYWORDS or dst == src or dst not in names or src not in names:
        return None
    if not _standalone(part.clean, hit.start()):
        return None
    shift = part.opening + 1
    gotos = [(shift + g.start(), shift + g.end()) for g in _gotos(part, second)]
    if not gotos or any(not _standalone(part.clean, begin) for begin, _ in gotos):
        return None
    copy = f'{dst} = {src};'
    indent = re.search(r'[ \t]*$', source[:hit.start()])[0]
    # the first label stays in front of the copy; the second one moves behind it
    edits = [(hit.start('second'), hit.end(), f'{dst} = {src};\n{indent}{second}:')]
    for begin, _ in gotos:
        edits.append((begin, begin, f'{copy} '))
    return edits, first, second, src


def _sinks(source, part, label_names, src):
    """Moves of `src = <number>;` past an early-return guard that follows it, in the arms that jump to the join."""
    clean = part.clean
    moves = []
    for hit in _FLAG.finditer(clean, part.opening + 1, part.end):
        if hit['var'] != src or not _standalone(clean, hit.start()):
            continue
        guard = re.compile(r'\s*if\s*\(').match(clean, hit.end())
        if not guard:
            continue
        condition = close(clean, guard.end() - 1)
        if not condition:
            continue
        inside = clean[guard.end() - 1:condition]
        if re.search(rf'\b{re.escape(src)}\b', inside):
            continue
        body = re.compile(r'\s*\{\s*return\s*;\s*\}').match(clean, condition)
        if body:
            stop = body.end()
        else:
            body = re.compile(r'\s*return\s*;').match(clean, condition)
            if not body:
                continue
            stop = body.end()
        if re.match(r'\s*else\b', clean[stop:stop + 8]):
            continue
        # only an arm that goes on to jump to the join (or falls into it) is one of the join's arms
        follow = clean[stop:stop + 60]
        if not re.match(rf'\s*(?:goto\s+(?:{"|".join(map(re.escape, label_names))})\s*;|[}}]|case\b|{"|".join(map(re.escape, label_names))}\s*:)', follow):
            continue
        indent = re.search(r'[ \t]*$', clean[:hit.start()])[0]
        line = source[hit.start():hit.end()]
        cut = hit.end() + (1 if clean[hit.end():hit.end() + 1] == '\n' else 0)
        start = hit.start() - len(indent)
        moves.append([(start, cut, ''), (stop, stop, f'\n{indent}{line}')])
    return moves


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    names = _locals(part)
    result = []
    for hit in _JOIN.finditer(part.clean, part.opening + 1, part.end):
        found = _anchor(source, part, hit, names)
        if not found:
            continue
        edits, first, second, src = found
        result.append((FAMILY, edit(source, edits)))
        moves = _sinks(source, part, (first, second), src)
        if moves:
            result.append((SINK_FAMILY, edit(source, edits + [piece for move in moves for piece in move])))
    return list(dict.fromkeys(result))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
