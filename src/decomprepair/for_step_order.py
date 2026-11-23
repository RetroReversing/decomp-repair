"""The two steps of a `for` header swapped: `for (...; ...; i++, p += 3)` as `for (...; ...; p += 3, i++)` (GCC 2.7.2, KMC).

loop.c emits a derived address's step right after the step of the induction variable it comes from, and the scheduler
keeps those two in the order they were emitted: with `i++, p += 3` the loop's end is `addiu i; addiu giv` and with
`p += 3, i++` it is `addiu giv; addiu i`. The target of a 559-instruction N64 display-list builder (`gcc-2.7.2-kmc
-G0 -mips3 -mgp32 -mfp32 -O2`) had the second, two rows in a function whose other rows already matched (55 -> 35 with
the swap alone; the lockstep pointer is the loop pass's own giv, `cursor_lockstep_fold`).

`variants` writes each `for` header with exactly two comma-separated steps once with the steps swapped
(`for_step_order`). The steps must be plain statements of a counter or pointer (`i++`, `p += 3`, `++i`, `i = i + 1`):
a step that reads what the other writes, or that calls, is left alone, since the swap would change the program.
"""
import re

from .csource import find
from .pattern_repairs import close

FAMILY = 'for_step_order'
FAMILIES = (FAMILY,)

_FOR = re.compile(r'\bfor\s*\(')
_ID = r'[A-Za-z_]\w*'
_STEP = re.compile(rf'\s*(?:(?:\+\+|--)\s*(?P<a>{_ID})|(?P<b>{_ID})\s*(?:\+\+|--)|(?P<c>{_ID})\s*(?:[-+|&^]=|<<=|>>=)\s*[\w.\->\[\]]+|'
                   rf'(?P<d>{_ID})\s*=\s*(?P=d)\s*[-+]\s*[\w.\->\[\]]+)\s*')


def _steps(text):
    parts, depth, start = [], 0, 0
    for pos, char in enumerate(text):
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(text[start:pos])
            start = pos + 1
    parts.append(text[start:])
    return parts


def _target(step):
    hit = _STEP.fullmatch(step)
    return (hit['a'] or hit['b'] or hit['c'] or hit['d']) if hit else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    out = []
    for hit in _FOR.finditer(source, span[0], span[1]):
        end = close(source, hit.end() - 1)
        if not end or end > span[1]:
            continue
        header = source[hit.end():end - 1]
        parts = header.split(';')
        if len(parts) != 3:
            continue
        steps = _steps(parts[2])
        if len(steps) != 2:
            continue
        names = [_target(step) for step in steps]
        if None in names or names[0] == names[1]:
            continue
        # one step reading what the other writes would change meaning when swapped
        if any(re.search(rf'(?<![\w.>]){re.escape(names[1 - k])}\b', re.sub(r'^\s*[^\s=+\-|&^<>]*', '', steps[k]))
               for k in range(2)):
            continue
        swapped = steps[1].strip() + ', ' + steps[0].strip()
        lead = parts[2][:len(parts[2]) - len(parts[2].lstrip())]
        out.append((FAMILY, source[:hit.end()] + ';'.join(parts[:2]) + ';' + lead + swapped + source[end - 1:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
