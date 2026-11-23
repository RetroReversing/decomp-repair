"""A copy that the `then` arm overwrites, moved into the `else` arm, with the source's later reuse of it split off.

`y = x; if (x < 0) { y = x + w; } else if (w < y) { y -= w; }` copies `x` before the branch although the `then` arm
never reads the copy. GCC's cse runs along the path the branch jumps to, and makes `y` and `x` one quantity there: the
compare reads whichever register it ranks first, the longer-lived of the two. When `x` is also the variable the
function reuses for an unrelated value further down (`x = (u32) f;`) it outlives `y`, the compare reads `x`, and the
two registers coalesce. Written as the target's C reads, the copy opens the `else` arm and the later value has a
local of its own: then `y` is the longer-lived and the compare reads it. Each edit alone is worse (835 and 690);
together 240 -> 135 in one 242-instruction heightmap filter (KMC GCC 2.7.2).

A proposal takes `Y = X;` directly above `if (...) {...} else ...` whose `then` arm assigns `Y` before it reads it, and:
(1) writes the copy as the first statement of the `else` (an `else if` becomes `else { Y = X; if ... }`); and (2) when
`X` is also assigned a fresh value after the whole `if` (a plain `X = ...;` that does not read `X`, with every later
reference of `X` after it), renames that later web to a new local. The combination first, then each alone, for each
such copy; at most 6 proposals."""
import re

from .integer_repair_support import INTEGER, edit, view

FAMILY = 'else_arm_copy_split'
FAMILIES = (FAMILY,)
LIMIT = 6

_ID = r'[A-Za-z_]\w*'
_COPY = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<y>{_ID})[ \t]*=[ \t]*(?P<x>{_ID})[ \t]*;[ \t]*\n(?P<next>[ \t]*)(?=if[ \t]*\()')
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>{INTEGER})\s+(?P<names>{_ID}(?:\s*,\s*{_ID})*)\s*;[ \t]*$')


def _match(text, at, opener):
    closer = {'{': '}', '(': ')'}[opener]
    depth = 0
    for position in range(at, len(text)):
        depth += text[position] == opener
        depth -= text[position] == closer
        if depth == 0:
            return position
    return None


def _statement(clean, at):
    """(end, index of the `then` block's `{`, index of its `}`, where the `else` part starts) of the `if` at `at`."""
    head = re.compile(r'if\s*\(').match(clean, at)
    if not head:
        return None
    close = _match(clean, head.end() - 1, '(')
    block = re.compile(r'\s*\{').match(clean, close + 1) if close is not None else None
    if not block:
        return None
    opening = block.end() - 1
    closing = _match(clean, opening, '{')
    if closing is None:
        return None
    stop, tail = closing + 1, None
    while True:
        other = re.compile(r'\s*else\b\s*').match(clean, stop)
        if not other:
            return stop, opening, closing, tail
        tail = tail or other.start()
        if clean.startswith('if', other.end()):
            sub = _statement(clean, other.end())
            if not sub:
                return None
            stop = sub[0]
            continue
        if not clean.startswith('{', other.end()):
            return None
        end = _match(clean, other.end(), '{')
        if end is None:
            return None
        stop = end + 1


def _refs(clean, name, lo, hi):
    return [lo + m.start() for m in re.finditer(rf'(?<![\w.]){re.escape(name)}\b', clean[lo:hi])]


def variants(source, name):
    """Proposals: the copy opening the else arm and the later web of its source split off, and each alone."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    locals_ = {local for decl in _DECL.finditer(clean, part.opening + 1, part.end) for local in re.findall(_ID, decl['names'])}
    out = []
    for hit in _COPY.finditer(clean, part.opening + 1, part.end):
        y, x = hit['y'], hit['x']
        if y == x or y not in locals_:
            continue
        chain = _statement(clean, hit.end())
        if not chain or chain[3] is None:
            continue
        stop, opening, closing, tail = chain
        inner = _refs(clean, y, opening, closing)
        assigned = re.compile(rf'{re.escape(y)}\s*=(?!=)([^;]*);').match(clean, inner[0]) if inner else None
        if not assigned or re.search(rf'\b{re.escape(y)}\b', assigned.group(1)):
            continue
        if re.search(rf'(?<![\w.]){re.escape(x)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[hit.end():closing]):
            continue
        indent = hit['indent']
        other = re.compile(r'\s*else\s*').match(clean, tail)
        if clean.startswith('{', other.end()):
            sink = [(other.end() + 1, other.end() + 1, f'\n{indent}    {y} = {x};')]
        else:
            nested = source[other.end():stop].replace('\n', '\n    ')
            sink = [(other.end(), stop, f'{{\n{indent}    {y} = {x};\n{indent}    {nested}\n{indent}}}')]
        sink.append((hit.start(), hit.end(), hit['next']))
        after = _refs(clean, x, stop, part.end)
        split = None
        if after:
            first = after[0]
            line = clean[clean.rfind('\n', 0, first) + 1:first]
            assign = re.compile(rf'{re.escape(x)}\s*=(?!=)([^;]*);').match(clean, first)
            declared = [decl for decl in _DECL.finditer(clean, part.opening + 1, part.end)
                        if re.search(rf'\b{re.escape(x)}\b', decl['names'])]
            if not line.strip() and assign and declared and not re.search(rf'\b{re.escape(x)}\b', assign.group(1)):
                fresh, number = f'{x}_next', 0
                while re.search(rf'\b{fresh}\b', clean):
                    number += 1
                    fresh = f'{x}_next{number}'
                split = [(at, at + len(x), fresh) for at in after]
                split.append((part.opening + 1, part.opening + 1, f"\n    {declared[-1]['type']} {fresh};"))
        if split:
            out.append(edit(source, sink + split))
        out.append(edit(source, sink))
        if split:
            out.append(edit(source, split))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 98}  # the registry: no caller wiring (registry.py)
