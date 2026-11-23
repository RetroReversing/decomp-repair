"""Trailing call arguments a callee's matched definition does not take, dropped.

m2c passes whatever the argument registers still held when it cannot tell a callee's arity: a 1300-instruction KMC GCC
2.7.2 controller routine called `updateActorSpeedScale(arg0, temp_a1)`, `finishEntityAndUnlink(arg0, temp_a1)` and
`setActorAssetIndex(arg0, idx, temp_a2, temp_a3)` where the matched callees take one, one and two parameters. The extra
arguments keep values alive into the call and move the registers around it (7000 -> 6935 with the three dropped; the
fourth, whose value the target did load into `$a1` for its own use, stayed). `target_call_arity_repairs` reads arity
from the target's register setup, which the registers' leftover values defeat here; the matched definitions say it
outright.

callee_arity_trim
    For each callee whose matched definition (in `callees`) takes N parameters and is called with more, the calls
    lose their arguments past N, when those are plain names (nothing evaluated is dropped). Every callee together
    first, then each alone. The judge decides; a drop that is worse means the target used the value."""
import re

from .csource import _blank, find
from .missing_call_argument_local import _definition

FAMILY = 'callee_arity_trim'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'


def _arguments(text):
    """(start, end) of each top-level argument inside a call's parentheses `text` (without them)."""
    out, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == ',' and depth == 0:
            out.append((start, index))
            start = index + 1
    if text.strip():
        out.append((start, len(text)))
    return out


def variants(source, name, callees=''):
    span = find(source, name)
    if not span or not callees:
        return []
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not head:
        return []
    opening = span[0] + head.end() - 1
    per = {}
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', clean[:span[1]]):
        if hit.start() < opening or hit[1] in ('if', 'while', 'for', 'switch', 'return', 'sizeof'):
            continue
        params = _definition(callees, hit[1])
        if params is None:
            continue
        count = 0 if [p for p in params if p.strip() and p.strip() != 'void'] == [] else len(params)
        depth, close = 0, None
        for index in range(hit.end() - 1, span[1]):
            depth += (clean[index] == '(') - (clean[index] == ')')
            if depth == 0:
                close = index
                break
        if close is None:
            continue
        inner = clean[hit.end():close]
        args = _arguments(inner)
        if len(args) <= count:
            continue
        dropped = [inner[a:b].strip() for a, b in args[count:]]
        if not all(re.fullmatch(IDENT, d) for d in dropped):
            continue
        cut = hit.end() + (args[count - 1][1] if count else 0)
        per.setdefault(hit[1], []).append((cut, close))
    out = []
    edits = [e for sites in per.values() for e in sites]
    if len(per) > 1:
        child = source
        for start, end in sorted(edits, reverse=True):
            child = child[:start] + child[end:]
        out.append((FAMILY, child))
    for sites in per.values():
        child = source
        for start, end in sorted(sites, reverse=True):
            child = child[:start] + child[end:]
        out.append((FAMILY, child))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'callees')}
