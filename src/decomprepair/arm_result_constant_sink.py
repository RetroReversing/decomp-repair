"""A switch arm's constant result written at the arm's `break`, in every arm at once, so it never lives across a call.

An interpreter loop sets its handler result in each arm of the opcode `switch` and tests it after the switch. m2c
writes the constant where the target's delay slot computed it (`result = 0; if (..) { f(); ... }`, `result = 0;
reset(v, 1); break;`), which is before the arm's calls. One such arm is enough to make the result a pseudo that
crosses a call: global.c gives it a saved register (`$s0`) in every arm, where the target keeps it in `$a0`. Each arm
moved alone is worse (two arms of a 1315-instruction KMC GCC 2.7.2 sound-sequence interpreter, `-G0 -mips3 -mgp32
-mfp32 -O2`: 19185 -> 19245 and 19385); both together 15930, so the family's first child moves every arm.

`arm_result_constant_sink`
    For a local `V` that the arms of a `switch` assign, each top-level `V = K;` (`K` a literal or `NULL`) in a
    `case` arm that ends in `break;`, with no read of `V`, no label and no `return` after it in the arm, moves to just
    before that `break;`. A `goto L;` after it in the arm is allowed only when `L:` is followed by `V = K;` with the
    same `K` (the path still sets it). Children: every arm at once, then each arm alone (at most eight).

The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'arm_result_constant_sink'
FAMILIES = (FAMILY,)
LIMIT = 8
VALUE = r'(?:-?\s*' + NUMBER + r'|NULL|\(\s*void\s*\*\s*\)\s*0)'


def _arms(clean, opening, end):
    """(start, stop) of each top-level `case`/`default` arm's statements in the switch body."""
    labels = []
    depth = 0
    at = opening + 1
    while at < end - 1:
        char = clean[at]
        if char in '{(':
            depth += 1
        elif char in '})':
            depth -= 1
        elif depth == 0 and not re.match(r'\w', clean[at - 1]):
            hit = re.match(r'(?:case\b[^:;{}]*|default\s*):(?!:)', clean[at:end])
            if hit:
                labels.append((at, at + hit.end()))
                at += hit.end()
                continue
        at += 1
    return [(body, labels[n + 1][0] if n + 1 < len(labels) else end - 1) for n, (_, body) in enumerate(labels)]


def _python_top_statements(clean, start, stop):
    """Start offsets of the statements at the top level of `clean[start:stop]`."""
    starts = []
    depth = 0
    fresh = True
    at = start
    while at < stop:
        char = clean[at]
        if fresh and not char.isspace():
            if depth == 0:
                starts.append(at)
            fresh = False
        if char in '({[':
            depth += 1
        elif char in ')]}':
            depth -= 1
            if char == '}' and depth == 0:
                fresh = True
        elif char == ';' and depth == 0:
            fresh = True
        at += 1
    return starts


_top_statements = _python_top_statements
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _top_statements(clean, start, stop):
        found = _scan.top_statement_starts(clean, start, stop)
        return _python_top_statements(clean, start, stop) if found is NotImplemented else found


def _moves(clean, part, opening, end):
    moves = []
    body = clean[part.opening:part.end]
    for start, stop in _arms(clean, opening, end):
        text = clean[start:stop].rstrip()
        final = re.search(r'\bbreak\s*;$', text)
        if not final:
            continue
        final_at = start + final.start()
        for at in _top_statements(clean, start, final_at):
            hit = re.match(r'(' + IDENT + r')\s*=\s*(' + VALUE + r')\s*;', clean[at:final_at])
            if not hit:
                continue
            name, value = hit[1], re.sub(r'\s+', '', hit[2])
            rest = clean[at + hit.end():final_at]
            if not rest.strip():
                continue
            reads = [m for m in re.finditer(r'\b' + re.escape(name) + r'\b', rest)
                     if not re.match(r'\s*=(?!=)', rest[m.end():])]
            if reads or re.search(r'\breturn\b', rest) or re.search(r'(?m)(?:^|[;{}])\s*(?!default\b)' + IDENT + r'\s*:(?!:)', rest) \
                    or re.search(r'\b(?:case|default)\b', rest) or re.search(r'\b(?:continue)\b', rest):
                continue
            # a break inside the arm that leaves the switch (not a nested switch/loop's) would skip the sunk value
            if any(not _nested(rest, m.start()) for m in re.finditer(r'\bbreak\b', rest)):
                continue
            safe = True
            for goto in re.finditer(r'\bgoto\s+(' + IDENT + r')\s*;', rest):
                target = re.search(r'\b' + re.escape(goto[1]) + r'\s*:(?!:)((?:\s*' + IDENT + r'\s*:(?!:))*)\s*'
                                   + re.escape(name) + r'\s*=\s*(' + VALUE + r')\s*;', body)
                if not target or re.sub(r'\s+', '', target[2]) != value:
                    safe = False
                    break
            if not safe:
                continue
            moves.append((at, at + hit.end(), final_at, f'{name} = {hit[2].strip()};'))
            break
    return moves


def _nested(text, at):
    depth = 0
    for pos in range(at - 1, -1, -1):
        if text[pos] == '}':
            depth += 1
        elif text[pos] == '{':
            if depth:
                depth -= 1
                continue
            head = text[:pos].rstrip()
            if re.search(r'\bdo$', head):
                return True
            if head.endswith(')'):
                level = 0
                for back in range(len(head) - 1, -1, -1):
                    level += (head[back] == ')') - (head[back] == '(')
                    if level == 0:
                        if re.search(r'\b(?:switch|for|while)\s*$', head[:back]):
                            return True
                        break
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    groups = []
    for switch in re.finditer(r'\bswitch\s*\(', clean[part.opening:part.end]):
        paren = part.opening + switch.end() - 1
        after = close(clean, paren, '(', ')')
        brace = re.match(r'\s*{', clean[after:]) if after else None
        if not brace:
            continue
        opening = after + brace.end() - 1
        end = close(clean, opening, '{', '}')
        if end:
            groups.append(_moves(clean, part, opening, end))
    results = []
    for moves in groups:
        if not moves:
            continue
        def apply(chosen):
            edits = []
            for start, stop, final_at, statement in chosen:
                line = source.rfind('\n', 0, start) + 1
                line_end = source.find('\n', stop)
                if not source[line:start].strip() and not source[stop:line_end].strip():
                    edits.append((line, line_end + 1, ''))
                else:
                    edits.append((start, stop, ''))
                indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, final_at) + 1:]).group(0)
                edits.append((final_at, final_at, f'{statement}\n{indent}'))
            return edit(source, edits)
        results.append((FAMILY, apply(moves)))
        if len(moves) > 1:
            for move in moves[:LIMIT]:
                results.append((FAMILY, apply([move])))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
