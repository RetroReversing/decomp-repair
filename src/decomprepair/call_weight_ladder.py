"""Calls wrapped in one-shot scopes several deep, a few calls at once, so the saved registers' allocation order moves.

GCC 2.x hands the saved registers to pseudos in order of `floor_log2(refs) * refs / live length` (global.c), and flow.c
counts every reference once more per loop it sits in. `do { f(p, q); } while (0);` is one loop more round the call, at
no instruction or run-time cost, so it adds one reference to `p` and one to `q`; written three deep it adds three.
`argument_weight_scope` wraps one call once and `loop_weight_set` the steps of the loop locals; a function whose saved
registers are in the wrong order because the *parameter, the list pointers and a flag* weigh against each other needs the
calls that use them wrapped at different depths at once. Each wrapper alone moves nothing (the greedy chain's
one-edit steps score the same or worse), so the combination is one child.

A 88-instruction KMC N64 list walk (three nested pointer loops over an object list, one parameter passed to six calls,
a flag copied into a temp at every loop head; `-G0 -mips3 -mgp32 -mfp32 -O2`) sat at 110 with the parameter, the flag,
the list pointers and the object pointer in the wrong register order. Counting weighted references from the source (each
reference is one plus the loop depth it sits at; the `-dl -dg` table agreed to the digit: the flag's 17 references over
39 live instructions) showed the target's order (parameter, sibling list, object, flag) needs the flag below the object,
which no change to the loops did: the loops stay as the draft has them and the calls that name the object, the parameter
and the sibling pointer are wrapped (the two calls that open the first flag arm three deep, the last loop's call run
twice: 110 -> 0 as one child, the 85th of 203 children from the saved best). Those are hypotheses read from the
allocation table, not confirmed in the compiler source. The wrappers are scaffolding a developer would not have written: polishing removes them once the match is
recorded.

`variants` takes the calls that name at least one declared local or parameter, and the runs of consecutive calls as one
unit as well, and offers every choice of up to three units at depth one to three (six wrappers at most), one child for
each distinct change in the weighted references of the names (two choices that move every name alike are one child, the
one with fewer wrappers). The fewest wrappers come first. The judge decides, and no child is a verdict."""
import itertools
import re

from .integer_repair_support import IDENT, edit, view
from .loop_weight_set_repairs import _declarations_end

FAMILY = 'call_weight_ladder'
FAMILIES = (FAMILY,)
LIMIT = 240
MAX_UNITS = 3
MAX_DEPTH = 3
MAX_WRAPPERS = 6
_CALL = re.compile(rf'(?<=[;{{}}])(?P<lead>[ \t\r\n]*)(?P<call>(?!(?:if|while|for|switch|return|sizeof|do|else)\b){IDENT}\s*\([^;{{}}]*\))\s*;')


def _parameters(part):
    head = part.clean[:part.opening]
    signature = head[head.rindex('(') + 1:head.rindex(')')] if '(' in head and ')' in head else ''
    return [m[1] for m in (re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', piece) for piece in signature.split(',')) if m]


def _declared(part):
    end = _declarations_end(part.clean, part)
    text = part.clean[part.opening + 1:part.opening + 1 + end]
    names = {m['n'] for m in re.finditer(rf'(?<=[;{{}}])\s*(?:{IDENT}\s+)+\**\s*(?P<n>{IDENT})\s*(?:\[[^\]]*\])?\s*;', ';' + text)}
    return names | set(_parameters(part))


def _wrap(text, depth):
    return 'do { ' * depth + text.strip() + ' } while (0);' * depth


def units(source, name):
    """[(start, end, text, {name: references})] of the call statements and of runs of consecutive ones."""
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    names = _declared(part)
    calls = [m for m in _CALL.finditer(part.clean, part.opening + 1, part.end)]
    found = []
    for index, hit in enumerate(calls):
        run = [hit]
        found.append(run[:])
        for follower in calls[index + 1:]:
            if part.clean[run[-1].end():follower.start('call')].strip():
                break
            run.append(follower)
            found.append(run[:])
    result = []
    for run in found:
        start, end = run[0].start('call'), run[-1].end()
        text = source[start:end]
        counts = {n: len(re.findall(rf'(?<![\w.>]){re.escape(n)}\b', part.clean[start:end])) for n in names}
        counts = {n: c for n, c in counts.items() if c}
        if counts:
            result.append((start, end, text, counts))
    return result


def vectors(found):
    """[(wrappers, {unit index: depth}, delta)] by the fewest wrappers, one for each distinct delta of the names."""
    seen, out = set(), []
    for count in range(1, MAX_UNITS + 1):
        for chosen in itertools.combinations(range(len(found)), count):
            for depths in itertools.product(range(1, MAX_DEPTH + 1), repeat=count):
                total = sum(depths)
                if total > MAX_WRAPPERS:
                    continue
                # a run and one of its own calls overlap: one scope per statement
                spans = [(found[i][0], found[i][1]) for i in chosen]
                if any(s[0] < t[1] and t[0] < s[1] for s, t in itertools.combinations(spans, 2)):
                    continue
                delta = {}
                for i, depth in zip(chosen, depths):
                    for n, c in found[i][3].items():
                        delta[n] = delta.get(n, 0) + c * depth
                key = tuple(sorted(delta.items()))
                if key in seen:
                    continue
                seen.add(key)
                out.append((total, dict(zip(chosen, depths)), delta))
    out.sort(key=lambda item: (item[0], len(item[1]), sorted(item[1].items())))
    return out


def variants(source, name):
    found = units(source, name)
    if len(found) < 2:
        return []
    result = []
    for total, picks, delta in vectors(found)[:LIMIT]:
        if len(delta) < 2:
            continue
        result.append((FAMILY, edit(source, [(found[i][0], found[i][1], _wrap(found[i][2], depth))
                                              for i, depth in picks.items()])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
