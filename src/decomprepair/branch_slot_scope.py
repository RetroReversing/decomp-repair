"""Pin a constant initializer in front of a branch with a one-statement `do { } while (0)`, so it fills the branch's slot.

GCC 2.7.2 (KMC, N64) schedules each basic block before register allocation. An independent register initializer
written just before an `if` is moved by that scheduler to wherever a load's latency leaves a hole, usually in front of
the loads that fed the branch, and the delay-slot filler then has nothing to take: the branch keeps a `nop`, or the
slot gets the wrong instruction. The loop notes a `do { } while (0)` leaves behind are scheduling boundaries and
nothing else survives, so `do { i = 0; } while (0);` right before the `if` keeps `i = 0` as the block's last
instruction, and the filler puts it in the branch's delay slot.

One function matched this way from 10 to 0 (COMPILER_MATCHING_LEARNINGS.md): the first statement of the guarded
inner loop was `i = 0;`, and the target had it in the guard's delay slot, after both volatile loads, ahead of the two
register copies. Neither step helped alone: moving the copy out of the delay slot scored 60, the bare hoist 120, only
the wrapped hoist together with the copy sunk to the top of the body reached 0. So both are proposed as one child.

A proposal hoists the first body statement `v = CONST;` of an `if (c) { ... }` to just before the `if`, wrapped; with
the plain copies `a = b;` that stood directly before the `if` optionally sunk to the top of the body. It is proposed
only when the variable is used nowhere else outside the body (the hoist runs when the guard is false too), and the
guard has no side effects. Only MIPS is proposed (the GCC scheduler).
"""
import re

from .csource import _blank, find

FAMILY = 'branch_slot_scope'
FAMILIES = (FAMILY,)
LIMIT = 16

_ID = r'[A-Za-z_]\w*'
_NUMBER = r'[-+]?\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_INIT = re.compile(rf'\s*({_ID})\s*=\s*({_NUMBER})\s*;')
_COPY = re.compile(rf'({_ID})\s*=\s*({_ID})\s*;')
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\w\s*\(')


def _close(clean, start, left, right):
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


def _preceding_copies(clean, lower, at):
    """(start, end) of each plain `a = b;` statement standing directly before `at`, in source order."""
    found, end = [], at
    while True:
        text = clean[lower:end].rstrip()
        cut = max(text.rfind(';', 0, len(text) - 1), text.rfind('{'), text.rfind('}')) + 1
        hit = _COPY.fullmatch(text[cut:].strip()) if text.endswith(';') else None
        if not hit or hit[1] == hit[2]:
            return found
        start = lower + cut + len(text[cut:]) - len(text[cut:].lstrip())
        found.insert(0, (start, lower + len(text)))
        end = start


def _pad(source, at):
    line = source[source.rfind('\n', 0, at) + 1:at]
    return line if not line.strip() else re.match(r'\s*', line)[0]


def _uses(text, name):
    return len(re.findall(rf'(?<![\w.>]){re.escape(name)}\b', text))


def variants(source, name, arch='mips', asm='', header=''):
    """Proposals: a constant initializer hoisted before its guard in a one-shot scope, with and without the copies sunk."""
    if arch != 'mips':
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    out = []
    for guard in re.finditer(r'\bif\s*\(', clean[opening:closing]):
        at = opening + guard.start()
        paren = opening + guard.end() - 1
        paren_end = _close(clean, paren, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, paren_end) if paren_end else None
        body_end = _close(clean, brace.end() - 1, '{', '}') if brace else None
        init = _INIT.match(clean, brace.end()) if body_end else None
        if not init:
            continue
        condition = clean[paren + 1:paren_end - 1]
        variable = init[1]
        outside = clean[opening + 1:brace.end()] + clean[body_end:closing]
        declared = re.search(rf'(?m)^[ \t]*(?:(?:unsigned|signed|register)\s+)*{_ID}(?:\s+|\s*\*+\s*){variable}\s*;', outside)
        if (not declared or _uses(outside, variable) != 1 or _EFFECT.search(condition) or _uses(condition, variable)):
            continue
        pad = _pad(source, at)
        literal = re.sub(r'\s+', '', init[2])
        scope = f'do {{\n{pad}    {variable} = {literal};\n{pad}}} while (0);\n{pad}'
        copies = _preceding_copies(clean, opening + 1, at)
        for k in range(len(copies) + 1):
            sunk = copies[len(copies) - k:]
            targets = [_COPY.fullmatch(clean[a:b])[1] for a, b in sunk]
            if any(_uses(condition, t) or _uses(outside, t) != 2 for t in targets):
                continue
            edits = [(init.start(), init.end(), ''.join(f'\n{pad}  {source[a:b]}' for a, b in sunk)),
                     (at, at, scope)] + [(a, b + len(clean[b:]) - len(clean[b:].lstrip()), '') for a, b in sunk]
            new = source
            for a, b, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
                new = new[:a] + text + new[b:]
            out.append((FAMILY, new))
    seen, unique = set(), []
    for item in out:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]
