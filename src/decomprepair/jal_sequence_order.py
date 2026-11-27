"""Adjacent calls written in another order than the target's `jal`s, read from the whole call sequence.

gcc keeps calls in source order, so a run of call statements whose callees the target makes in another order is the
wrong program, and no register or scheduling rewrite fixes it. `target_call_order` reads this for calls to one function;
here the callees differ. A draft wrote

    update(a); update(a->child); draw(a); draw(a->child);

where the target's calls are update, draw, update, draw: each record updated and drawn in turn (140 points to go
before, 0 together with one store moved; 103 instructions, MIPS GCC). A run of call statements is rewritten only when
its callees appear nowhere in the target's `jal`s in that order but a window of the same callees does; calls to one
callee keep their order among themselves. The judge decides whether the new order is the target's.
"""
import re
from collections import Counter

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'jal_sequence_order'
FAMILIES = (FAMILY,)
LIMIT = 6

# one call statement on its own line: no result kept, so moving it changes nothing but the order of calls
CALL = re.compile(r'(?m)^[ \t]*(?P<f>(?!(?:if|while|for|switch|return|sizeof|do|else)\b)[A-Za-z_]\w*)'
                  r'[ \t]*\((?P<args>[^;{}\n]*)\);[ \t]*(?=\n)')
# arguments that do something themselves (a call, an assignment, a step): such a statement is left where it is
EFFECT = re.compile(r'(?<![\w)])(?!sizeof\b)[A-Za-z_]\w*\s*\(|\+\+|--|(?<![=!<>])=(?!=)')
JAL = re.compile(r'\bjal\s+([A-Za-z_.$][\w.$]*)')


def _runs(clean, start, end):
    """The runs of two or more call statements with only white space between them."""
    run = []
    for match in CALL.finditer(clean, start, end):
        if EFFECT.search(match['args']):
            continue
        if run and clean[run[-1].end():match.start()].strip():
            if len(run) > 1:
                yield run
            run = []
        run.append(match)
    if len(run) > 1:
        yield run


def _orders(callees, target):
    """The other orders of `callees` the target makes them in, or nothing when it already makes this one."""
    size = len(callees)
    windows = [target[i:i + size] for i in range(len(target) - size + 1)]
    if callees in windows:
        return []
    want = Counter(callees)
    found = []
    for window in windows:
        if Counter(window) == want and window not in found:
            found.append(window)
    return found


def variants(source, name, asm):
    span = find(source, name)
    target = JAL.findall(asm or '')
    if not span or len(target) < 2:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result, seen = [], set()
    for run in _runs(clean, opening, end):
        # the longest stretches first: a whole run in the target's order is one child
        for size in range(len(run), 1, -1):
            for at in range(len(run) - size + 1):
                part = run[at:at + size]
                for order in _orders([m['f'] for m in part], target):
                    waiting = {}
                    for match in part:
                        waiting.setdefault(match['f'], []).append(source[match.start():match.end()])
                    pieces = [waiting[callee].pop(0) for callee in order]
                    text, last = [source[:part[0].start()]], None
                    for match, piece in zip(part, pieces):
                        if last is not None:
                            text.append(source[last:match.start()])
                        text.append(piece)
                        last = match.end()
                    text = ''.join(text) + source[last:]
                    if text not in seen:
                        seen.add(text)
                        result.append((FAMILY, text))
                    if len(result) >= LIMIT:
                        return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 60,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
