"""A group of constant assignments moved to the other end of its run, in every arm that has the same run.

An `if`/`else if` chain whose arms each set the same locals to different constants (positions, then colours, say)
compiles to one bundle of register loads and reload stores per arm. Which group the source names first decides how
long each of those pseudos is live, so which of them gets a saved register and which is spilled, and where the first
scheduler puts the loads. The order is the same in every arm of the original, so a search that moves one statement,
or one arm, at a time makes every step on the way worse. On a 383-instruction N64 billboard builder (SN GCC,
`-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float -mfp32`) four arms set six `s16` corner values and four `u8`
colour values; moving the colour group below the last corner value in all four arms was one step from 2250 to 105,
which `statement_slide`, `identical_statement_comove` (one statement, equal text) and `paired_statement_moves` do not
offer. That the live lengths are the cause is a hypothesis read from the allocation dumps; the judge decides.

Only assignments of a literal to distinct plain locals whose address is never taken are moved, only within one
unbroken run of them, so no child changes what the function does. Only runs that two or more blocks share (the same
names in the same order, an arm may lack some) are offered.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'arm_constant_run_shift'
FAMILIES = (FAMILY,)
LIMIT = 96
_LITERAL = r"-?\s*(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)[uUlLfF]*"
_ASSIGN = re.compile(rf'(?<=[;{{}}])\s*\b({IDENT})\s*=\s*{_LITERAL}\s*;')


def _plain_local(body, local):
    """Declared as a scalar in this function, not `volatile` or `static`, and its address never taken."""
    declared = re.search(rf'(?m)(?:^|[;{{}}])[ \t]*((?:(?!return\b|goto\b|else\b){IDENT}[ \t]+)+)\**[ \t]*'
                         rf'(?:{IDENT}[ \t]*,[ \t]*)*{local}[ \t]*(?:[;,]|=)', body)
    if not declared or {'volatile', 'static', 'extern'} & set(declared[1].split()):
        return False
    return not re.search(rf'&\s*\(?\s*{local}\b', body)


def _runs(part):
    """Each unbroken run of two or more assignments, as [(name, start, end)] over the source."""
    body = part.clean[part.opening:part.end]
    known, runs, run = {}, [], []
    for match in _ASSIGN.finditer(part.clean, part.opening, part.end):
        local = match[1]
        if local not in known:
            known[local] = _plain_local(body, local)
        start = match.start(1)
        joined = run and not part.clean[run[-1][2]:start].strip()
        if not joined or not known[local] or local in {item[0] for item in run}:
            runs.append(run)
            run = []
        if known[local]:
            run.append((local, start, match.end()))
    runs.append(run)
    return [found for found in runs if len(found) >= 2]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    runs = _runs(part)
    result, seen, shapes = [], {source}, set()
    for reference in sorted(runs, key=len, reverse=True):
        names = [item[0] for item in reference]
        # The arms of one shape: the reference's names in the reference's order, at most a third of them missing.
        peers = [run for run in runs if 3 * len(run) >= 2 * len(names) and set(item[0] for item in run) <= set(names)
                 and [item[0] for item in run] == [n for n in names if n in {item[0] for item in run}]]
        if len(peers) < 2 or tuple(names) in shapes:
            continue
        shapes.add(tuple(names))
        # Short groups first: one statement is a slide other families make, but not in every arm at once.
        for size in range(1, len(names)):
            for first in range(len(names) - size + 1):
                group = set(names[first:first + size])
                for last in (True, False):
                    edits = []
                    for run in peers:
                        # An arm may lack one of the names (it was already set), but must hold most of the group.
                        held = [item for item in run if item[0] in group]
                        if 2 * len(held) <= size or len(held) == len(run):
                            continue
                        others = [item for item in run if item[0] not in group]
                        order = others + held if last else held + others
                        edits += [(old[1], old[2], source[new[1]:new[2]])
                                  for old, new in zip(run, order) if old != new]
                    if sum(any(run[0][1] <= e[0] < run[-1][2] for e in edits) for run in peers) < 2:
                        continue
                    text = source
                    for begin, end, replacement in sorted(edits, reverse=True):
                        text = text[:begin] + replacement + text[end:]
                    if text not in seen:
                        seen.add(text)
                        result.append((FAMILY, text))
                        if len(result) >= LIMIT:
                            return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 271}
