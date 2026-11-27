"""A parameter m2c reused as the narrowed return value, folded back into the flag local it was copied from.

When a parameter is dead after its last read, m2c keeps the returned value in its register by writing it back:

    var_s1 = 0;  ...  arg1 = 0 & 0xFF;  if (c) { ...  var_s1 = 1; ...  arg1 = var_s1 & 0xFF; }  return arg1;

The target is one flag shared by the whole function and masked once, `return var_s1 & 0xFF;` (KMC GCC 2.7.2 `-O2`: the
frame needs `$s1` for the flag and the two copies cost an extra `move $v0,$a1`; a 78-instruction N64 function at
110 -> 0 once the carrier was gone, after the draft passes had cleaned the rest).

A site is a final `return P;` of a parameter `P` where, after the function's last other use of `P`, one statement sets
`P = K & M;` (`K` a literal, optionally in parentheses) and the rest set `P = V & M;` for one local `V` that was set
`V = K;` earlier. The rewrite drops those statements and returns `V & M`. It is only offered when every other change of
`V` is followed, in the same or an enclosing block with no `return`/`goto` between, by one of the `P = V & M;`
statements, so `V & M` is what `P` held on every path.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'param_result_carrier_fold'
FAMILIES = (FAMILY,)
_RETURN = re.compile(rf'\breturn\s+({IDENT})\s*;\s*}}\s*$')
_INIT = rf'\(?\s*({NUMBER})\s*\)?\s*&\s*({NUMBER})'


def _params(clean, opening):
    head = clean[:opening]
    inner = head[head.rfind('(') + 1:head.rfind(')')]
    return {m[1] for m in re.finditer(rf'({IDENT})\s*(?:,|$)', inner)}


def _blocks(text):
    stack, spans = [], []
    for at, ch in enumerate(text):
        if ch == '{':
            stack.append(at)
        elif ch == '}' and stack:
            spans.append((stack.pop(), at))
    return spans


def _enclosing(spans, at):
    inside = [s for s in spans if s[0] < at < s[1]]
    return min(inside, key=lambda s: s[1] - s[0]) if inside else None


def _covers(spans, at, copy):
    block = _enclosing(spans, copy)
    return block is not None and block[0] < at < block[1]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body, base = part.body, part.opening + 1
    ending = _RETURN.search(body)
    if not ending or ending[1] not in _params(part.clean, part.opening):
        return []
    carrier = ending[1]
    sets = list(re.finditer(rf'(?m)^[ \t]*\b{carrier}\s*=\s*(.+?)\s*;[ \t]*\n?', body))
    first = next((m for m in sets if re.fullmatch(_INIT, m[1])), None)
    if not first:
        return []
    # Nothing but the carrier's own statements may use the parameter after the first one.
    rest = body[first.end():ending.start()]
    for m in sets:
        if m.start() >= first.end():
            rest = rest.replace(m[0], '', 1)
    if re.search(rf'\b{carrier}\b', rest):
        return []
    init = re.fullmatch(_INIT, first[1])
    const, mask = int(init[1].rstrip('uUlL'), 0), init[2]
    arms = [m for m in sets if m.start() > first.start()]
    copies = [re.fullmatch(rf'({IDENT})\s*&\s*{re.escape(mask)}', m[1]) for m in arms]
    if not arms or not all(copies) or len({c[1] for c in copies}) != 1:
        return []
    local = copies[0][1]
    if local == carrier or not re.search(rf'\b{local}\s*=\s*0*{const}[uUlL]*\s*;', body[:first.start()]):
        return []
    spans = _blocks(body)
    changes = [m.start() for m in re.finditer(rf'\b{local}\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\b{local}\s*(?:\+\+|--)', body[first.end():])]
    for at in (c + first.end() for c in changes):
        later = [a for a in arms if a.start() > at]
        if not any(_covers(spans, at, a.start()) and not re.search(r'\b(?:return|goto|break|continue)\b', body[at:a.start()])
                   for a in later):
            return []
    edits = [(base + m.start(), base + m.end(), '') for m in [first] + arms]
    edits.append((base + ending.start(), base + ending.end(), f'return {local} & {mask};\n}}'))
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
