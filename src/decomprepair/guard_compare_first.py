"""A guarded loop's counter initialised after the guard's compare: compare first, then the init, then the branch.

GCC 2.7.2 (KMC, N64) fills a branch's delay slot with an independent insn from before the branch, or from the
fall-through when the other path does not need its register (reorg.c, `fill_slots_from_thread`). A counter's `i = 0;`
written as the first statement of the guarded body (`if (flag < n) { i = 0; ... }`) is neither: the branch keeps a
`nop` and the assembler puts the `move` after it. Hoisting the init in front of the `if` puts it before the branch,
but then cse sees `i == 0` while it rewrites the compare, and a compare written `flag < n` (where `flag` is known to
be zero from an earlier branch) is replaced by `i < n`, then folded to `n != 0`: the `sltu $v0, $s3, $v0` the target
has disappears.

Computing the compare into a local first keeps both. The guard value is read by the branch, the init stands between
the compare and the branch, and the scheduler's delay-slot filler takes it into the branch's slot, while the compare
was already written when the init was seen. A two-branch guarded loop (a 16-bit and an 8-bit variant of the same loop,
KMC GCC 2.7.2) stood at 285 with the init in the body and at 85 with this one, every remaining row a register choice;
the cse reading is from cse.c (`fold_rtx` replaces a register by the newest register of its class of equal values),
a hypothesis that the measurement agrees with, and the judge decides each child.

The condition must be a relational test (`<`, `>`, `<=`, `>=`): a mask test (`flags & 4`) is computed by the branch itself
and gains nothing. A proposal turns `if (C) { v = LITERAL; rest }` into `g = (C); v = LITERAL; if (g) { rest }` with a new local `g`
declared at the top of the function. It is proposed only when the condition has no side effects and does not read `v`,
and when the first mention of `v` before the `if` and the first after it are both plain assignments (so the init now
also runs when the guard is false and no read can see it). Only MIPS is proposed (the GCC scheduler).
"""
import re

from .csource import _blank, find

FAMILY = 'guard_compare_first'
FAMILIES = (FAMILY,)
LIMIT = 32

_ID = r'[A-Za-z_]\w*'
_NUMBER = r'[-+]?\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_INIT = re.compile(rf'\s*({_ID})\s*=\s*({_NUMBER})\s*;')
_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|\w\s*\(')
_GUARD = re.compile(r'\bguard_value(?:_\d+)?\b')


def _close(clean, start, left, right):
    depth = 0
    for pos in range(start, len(clean)):
        depth += (clean[pos] == left) - (clean[pos] == right)
        if depth == 0:
            return pos + 1
    return None


def _mentions(text, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', text)]


def _assigned_first(text, name):
    """True when the first mention of `name` in `text` (past a declaration of it) is the left side of a plain `=`."""
    for at in _mentions(text, name):
        before = text[:at].rstrip()
        after = text[at + len(name):].lstrip()
        if after.startswith(';') and re.search(rf'(?:^|[;{{}}])\s*(?:(?:unsigned|signed|register)\s+)*{_ID}(?:\s*\*+)?$', before):
            continue  # its declaration
        return bool(re.match(r'=(?!=)', after))
    return True


def _declaration_end(clean, opening):
    """Offset just after the last declaration line of the function's top block (where its statements start)."""
    pos = opening + 1
    end = pos
    for line in re.finditer(r'[^\n]*\n?', clean[pos:]):
        text = line.group().strip()
        if not text:
            end = pos + line.end()
            continue
        if re.match(rf'(?:(?:unsigned|signed|register|volatile|const)\s+)*{_ID}(?:\s+|\s*\*+\s*){_ID}(?:\[[^\]]*\])*\s*;$', text) \
                and not re.match(r'(?:return|goto|else)\b', text):
            end = pos + line.end()
            continue
        break
    return end


def variants(source, name, arch='mips'):
    """Proposals: guards' compares computed into locals ahead of the counter inits that the bodies started with."""
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
    taken = set(_GUARD.findall(clean[opening:closing]))
    found = []
    for guard in re.finditer(r'\bif\s*\(', clean[opening:closing]):
        at = opening + guard.start()
        paren = opening + guard.end() - 1
        paren_end = _close(clean, paren, '(', ')')
        brace = re.compile(r'\s*\{').match(clean, paren_end) if paren_end else None
        body_end = _close(clean, brace.end() - 1, '{', '}') if brace else None
        init = _INIT.match(clean, brace.end()) if body_end else None
        if not init:
            continue
        condition = source[paren + 1:paren_end - 1]
        variable = init[1]
        if (_EFFECT.search(clean[paren + 1:paren_end - 1]) or _mentions(condition, variable)
                or not re.search(r'[<>]=?', condition.replace('->', '').replace('<<', '').replace('>>', ''))):
            continue
        outside = clean[opening + 1:brace.end()] + clean[body_end:closing]
        if (not _mentions(outside, variable) or not _assigned_first(clean[opening + 1:at], variable)
                or not _assigned_first(clean[body_end:closing], variable)):
            continue
        if not re.search(rf'(?m)^[ \t]*(?:(?:unsigned|signed|register)\s+)*{_ID}(?:\s+|\s*\*+\s*){variable}\s*;', outside):
            continue
        found.append((at, paren_end, condition.strip(), variable, re.sub(r'\s+', '', init[2]), init.start(), init.end()))
    if not found:
        return []
    places = sorted({opening + 1, _declaration_end(clean, opening)})

    def build(chosen, place):
        edits, names, n = [], [], 0
        for at, paren_end, condition, variable, literal, init_start, init_end in chosen:
            local = 'guard_value'
            while local in taken or local in names:
                n += 1
                local = f'guard_value_{n + 1}'
            names.append(local)
            line = source[source.rfind('\n', 0, at) + 1:at]
            pad = line if not line.strip() else re.match(r'\s*', line)[0]
            edits += [(at, paren_end, f'{local} = ({condition});\n{pad}{variable} = {literal};\n{pad}if ({local})'),
                      (init_start, init_end, '')]
        edits.append((place, place, ''.join(f'\n  u32 {local};' for local in names)))
        new = source
        for a, b, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
            new = new[:a] + text + new[b:]
        return new

    groups = [[one] for one in found]
    groups += [found[i:i + 2] for i in range(len(found) - 1)]  # neighbours: the arms of one if / else
    if len(found) > 2:
        groups.append(found)
    out = []
    for place in places:
        out += [(FAMILY, build(group, place)) for group in groups]
    seen, unique = set(), []
    for item in out:
        if item[1] not in seen and item[1] != source:
            seen.add(item[1])
            unique.append(item)
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 60}  # the registry: no caller wiring (registry.py)
