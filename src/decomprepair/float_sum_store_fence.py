"""A float sum split around a run of stores: the first add's operands swapped and a one-shot scope inside the run
(a KMC gcc 2.7.2 bounding-sphere function, `-G0 -mips3 -mgp32 -mfp32 -O2`, 25 -> 0).

m2c writes a sum of three products as `length = y2 + x2; <stores of the min/max values>; length += z2; <more stores>`
and the target had the two adds straddling the first stores with the registers of the products in the other order. Two
edits were needed and neither was enough alone (measured on that one function, hypotheses beyond the sched.c rule):

- the first add's operands in the target's order (`x2 + y2`): it fixes the product registers (the sum's destination
  is the register of the first operand) but alone leaves the first store hoisted above the third product, with the
  min/max register tied up (25 -> 220);
- a `do { } while (0);` inside the run of stores that sits between the two adds: sched.c makes the insn after a loop
  note depend on everything before it (in the source), so the stores after the scope stay behind the stores before it
  and the second add lands between them as the target has it. The scope's position in the run decides it: after the
  second of three stores (0); after the first (60); none (220). With the original operand order the right scope
  position was 10.

`variants` offers the swap, each scope position and each scope position with the swap, so the combination is one child.

Shape: `V = A + B;` (two plain names) then 2 to 8 plain stores (`x[k] = e;`, `*(T *)p = e;`, no call, jump or read of V)
and `V += C;` (or `V = V + C;`) in the same block.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_sum_store_fence'
FAMILIES = (FAMILY,)
FENCE = 'do { } while (0);\n'
MOST = 8
_FIRST = re.compile(rf'(?<![\w.>\]])(?P<v>{IDENT})\s*=\s*(?P<a>{IDENT})\s*\+\s*(?P<b>{IDENT})\s*;')
_JUMP = re.compile(r'\b(?:return|goto|break|continue|if|else|for|while|do|switch|case|asm|__asm__)\b')
_CALL = re.compile(rf'\b{IDENT}\s*\(\s*(?!\s*(?:\w+\s*)+\**\s*\))')


def _statements(clean, start, end):
    """(start, end) of each `;`-ended statement in clean[start:end], empty `{ }` blocks skipped; None when anything
    else is in the way (a block, a brace)."""
    out, at = [], start
    for hit in re.finditer(r';', clean[start:end]):
        stop = start + hit.end()
        text = re.sub(r'\{\s*\}', ' ', clean[at:stop])
        if re.search(r'[{}]', text):
            return None
        lead = len(clean[at:stop]) - len(clean[at:stop].lstrip())
        # a leading empty block belongs to the gap, not to the statement
        while True:
            empty = re.match(r'\{\s*\}\s*', clean[at + lead:stop])
            if not empty:
                break
            lead += empty.end()
        out.append((at + lead, stop))
        at = stop
    if clean[at:end].strip() and not re.fullmatch(r'(?:\s|\{\s*\})*', clean[at:end]):
        return None
    return out


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.body):
        return []
    clean, found = part.clean, []
    for first in _FIRST.finditer(clean, part.opening, part.end):
        v = first['v']
        add = re.compile(rf'(?<![\w.>\]]){re.escape(v)}\s*(?:\+=\s*{IDENT}|=\s*{re.escape(v)}\s*\+\s*{IDENT})\s*;')
        second = add.search(clean, first.end(), part.end)
        if not second:
            continue
        run = _statements(clean, first.end(), second.start())
        if run is None or not 2 <= len(run) <= MOST:
            continue
        texts = [clean[s:e] for s, e in run]
        if any(_JUMP.search(t) or _CALL.search(t) or re.search(rf'\b{re.escape(v)}\b', t) or '=' not in t
               or not re.match(r'\s*(?:\*|\(\*)?[\w(\[]', t) for t in texts):
            continue
        swap = [(first.start('a'), first.end('a'), first['b']), (first.start('b'), first.end('b'), first['a'])]
        if first['a'] == first['b']:
            continue
        fences = [[(run[k][0], run[k][0], FENCE)] for k in range(1, len(run))]
        found.append((FAMILY, edit(source, swap)))
        for fence in fences:
            found.append((FAMILY, edit(source, fence)))
        for fence in fences:
            found.append((FAMILY, edit(source, swap + fence)))
    seen, out = set(), []
    for family, text in found:
        if text != source and text not in seen:
            seen.add(text)
            out.append((family, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 30}  # the registry: no caller wiring (registry.py)
