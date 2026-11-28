"""m2c's second return variable, which always holds what the first one holds when the function returns.

GCC computes a function's result into `$v0` in the delay slots of the branches to its end (`move v0,s1`), and where
the result is a known number it loads the number instead. m2c reads that `$v0` as a variable of its own:

    ok = 1;                              ok = 1;
    ...                                  ...
    v = 1;               ->
    if (find() == 5) {                   if (find() == 5) {
        ok = 0;                              ok = 0;
        v = ok;                          }
    }                                    return ok;
    return v;

The extra variable is one more value for the register allocator and costs moves the target does not have.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 save-space check (141 instructions): 1670 -> 1356 from its repaired
draft, and a step of the chain to the exact match.

mirrored_return_value
    A local `v` that is only returned, and only ever assigned `w` (one other local) or numbers, where on every path to
    every `return v;` the two hold the same value (followed over the function's control flow: `w = K;` makes `w` known,
    `v = K;` makes them equal when `w` is known to be K). The `return`s read `w`; `v` and its assignments go. Both
    locals must be of one type and never have their address taken.

A hypothesis like every family's; the judge decides.
"""
import re
from collections import deque

from . import local_flow
from .csource import _blank
from .integer_repair_support import IDENT, edit

FAMILY = 'mirrored_return_value'
FAMILIES = (FAMILY,)

_NUMBER = r'-?(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?'
MAX_WORK = 100000


def _value(text):
    return int(text.rstrip('uU'), 0)


def _step(state, text, v, w):
    """(w's number or None, v's number or None, whether v == w) after one statement."""
    known_w, known_v, equal = state
    text = text.strip()
    hit = re.fullmatch(rf'({v}|{w})\s*=\s*({_NUMBER}|{v}|{w})\s*;', text)
    if hit:
        dest, value = hit.groups()
        if dest == w:
            known_w = _value(value) if re.fullmatch(_NUMBER, value) else known_v if value == v else known_w
        else:
            known_v = _value(value) if re.fullmatch(_NUMBER, value) else known_w if value == w else known_v
        equal = value in (v, w) and value != dest or (equal and value == dest) \
            or (known_w is not None and known_w == known_v)
        return known_w, known_v, equal
    for name in (v, w):
        if re.search(rf'(?<![\w.>]){name}\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^\-])?=(?!=))|(?:\+\+|--)\s*{name}\b', text):
            equal = False
            if name == w:
                known_w = None
            else:
                known_v = None
    return known_w, known_v, equal


def _meet(a, b):
    return (a[0] if a[0] == b[0] else None, a[1] if a[1] == b[1] else None, a[2] and b[2])


def _holds(flow, v, w):
    incoming = {flow.entry: (None, None, False)}
    pending = deque([flow.entry])
    work = 0
    while pending:
        index = pending.popleft()
        node = flow.nodes[index]
        text = flow.part.clean[node.start:node.end]
        if re.fullmatch(rf'\s*return\s+{v}\s*;\s*', text):
            continue
        out = _step(incoming[index], text, v, w)
        for nxt in node.successors:
            merged = out if nxt not in incoming else _meet(incoming[nxt], out)
            if incoming.get(nxt) != merged:
                incoming[nxt] = merged
                pending.append(nxt)
        work += 1
        if work > MAX_WORK:
            return False
    returned = [i for i, node in enumerate(flow.nodes)
                if re.fullmatch(rf'\s*return\s+{v}\s*;\s*', flow.part.clean[node.start:node.end])]
    return bool(returned) and all(i not in incoming or incoming[i][2] for i in returned)


def variants(source, name):
    flow = local_flow.analyze(source, name)
    if not flow or flow.entry is None or len(flow.locals) > 64:
        return []
    clean = _blank(source)
    opening, end = flow.part.opening, flow.part.end
    body = clean[opening:end]
    declared = {}
    for declaration in flow.locals:
        declared.setdefault(declaration['name'], []).append(declaration)
    out = []
    for v, declarations in declared.items():
        returns = len(re.findall(rf'\breturn\s+{v}\s*;', body))
        if len(declarations) != 1 or not returns:
            continue
        line = re.search(rf'(?m)^[ \t]*[A-Za-z_]\w*(?:\s*\*+\s*|\s+){v}\s*;[ \t]*\n', clean[opening:end])
        if not line:
            continue
        writes = list(re.finditer(rf'(?m)(?<![\w.>]){v}\s*=\s*({_NUMBER}|{IDENT})\s*;', body))
        # every other mention of v would be a read this rewrite does not carry over
        if len(re.findall(rf'(?<![\w.>]){v}\b', body)) != returns + len(writes) + 1:
            continue
        sources = {hit[1] for hit in writes if not re.fullmatch(_NUMBER, hit[1])}
        if len(sources) != 1:
            continue
        w = sources.pop()
        if (w == v or w not in declared or len(declared[w]) != 1
                or declared[w][0]['type'] != declarations[0]['type'] or not _holds(flow, v, w)):
            continue
        edits = [(opening + line.start(), opening + line.end(), '')]
        for hit in writes:
            start, stop = opening + hit.start(), opening + hit.end()
            before = clean[opening:start].rstrip()
            if not before.endswith((';', '{', '}', ':')):
                edits = None  # an unbraced body: dropping its statement would take the next one for it
                break
            left = source.rfind('\n', 0, start) + 1
            right = source.find('\n', stop)
            if not source[left:start].strip() and right >= 0 and not source[stop:right].strip():
                edits.append((left, right + 1, ''))
            else:
                edits.append((start, stop, ';' if before.endswith(':') else ''))
        if edits is None:
            continue
        for hit in re.finditer(rf'\breturn\s+({v})\s*;', body):
            edits.append((opening + hit.start(1), opening + hit.end(1), w))
        out.append((FAMILY, edit(source, edits)))
        if len(out) >= 4:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
