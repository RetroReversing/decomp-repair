"""A loop's `(p + (e))[i]` store or read, with `p + (e)` invariant in the loop, written through a pointer set before it.

A table builder that fills a second-level table writes into `tab + ((ent >> 7) + step)` at a varying index inside
its innermost loop. Spelled inline, loop.c moves the invariant base out of the loop as a register of its own, made
after the user variables set just before the loop; GCC 2.7.2 (KMC, N64) gives such a loop-made register its priority
from where loop.c places it and orders the base's shifts after the other loop-entry values, where the target computes
the base first. Written as a pointer local the programmer sets before the loop (`u16 *sb; ... sb = tab + ((ent >> 7)
+ step); do { sb[ix] = ...; } while (...);`), the base is a user variable with the life the source gives it, and its
shift comes where it is written. On a 681-instruction bit-stream decoder (KMC GCC 2.7.2) this was the step that took
the last pass from 410 to 110 once its loop-entry temporaries were written as the function's long-lived variables;
the same pointer set at any of the three statement boundaries between the last write of `ent` and the loop scored
110, 110 and 405 (the last one shortens the pointer's life and lifts it past a loop-made copy: a hypothesis read from
the allocation dumps, not from the compiler source).

A child for each such base and each statement boundary of the enclosing block from just after the last statement
that writes any variable the base reads, up to the loop itself: the pointer is declared after the block's own
declarations with the base's pointer type, set at that boundary, and every `(p + (e))[` of the same text in the loop
reads through it. Only a base whose variables the loop never writes (no assignment, `++` or `--`), whose pointer is a
plainly declared local or parameter, and that sits in a do-while, while or for loop with a braced body is offered.
A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'loop_subscript_base_pointer'
FAMILIES = (FAMILY,)
LIMIT = 24
_IDENT = r'[A-Za-z_]\w*'
_INNER = r'\((?:[^()]|\([^()]*\))*\)'
_SUB = re.compile(rf'\(\s*({_IDENT})\s*\+\s*({_INNER}|{_IDENT})\s*\)\s*\[')
_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')
_DECL = re.compile(r'\s*(?:(?:unsigned|signed|const|struct|union)\s+)*[A-Za-z_]\w*(?:\s*\*+\s*|\s+)[A-Za-z_]\w*'
                   r'(?:\s*\[[^\]]*\])?\s*(?:=[^;]*)?;')
_KEYWORDS = {'return', 'goto', 'break', 'continue', 'if', 'else', 'do', 'while', 'for', 'switch', 'case', 'default'}


def _close(clean, at, left='{', right='}'):
    depth = 0
    for i in range(at, len(clean)):
        depth += (clean[i] == left) - (clean[i] == right)
        if depth == 0:
            return i
    return None


def _open_of(clean, at, lo):
    depth = 0
    for i in range(at - 1, lo - 1, -1):
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                return i
            depth -= 1
    return None


def _loops(clean, lo, hi):
    """(statement start, body open, statement end) of every loop with a braced body."""
    out = []
    for loop in _LOOP.finditer(clean, lo, hi):
        at = loop.end() - 1
        if clean[at] == '(':
            shut = _close(clean, at, '(', ')')
            brace = re.compile(r'\s*\{').match(clean, shut + 1) if shut is not None else None
            if not brace:
                continue
            at = brace.end() - 1
        end = _close(clean, at)
        if end is None:
            continue
        if clean[loop.start():loop.start() + 2] == 'do':
            tail = re.compile(r'\s*while\s*\(').match(clean, end + 1)
            shut = _close(clean, tail.end() - 1, '(', ')') if tail else None
            if shut is None:
                continue
            end = shut + 1
        out.append((loop.start(), at, end))
    return out


def _writes(text, var):
    v = re.escape(var)
    return re.search(rf'\b{v}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{v}\b|\b{v}\s*(?:\+\+|--)', text)


def _statements(clean, opening, closing):
    """Offsets just after each top-level statement of the block, and where its declarations end."""
    ends, depth, i, decl_end = [], 0, opening + 1, None
    while i < closing:
        ch = clean[i]
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
            if ch == '}' and depth == 0 and not re.match(r'\s*(?:while\b|else\b)', clean[i + 1:closing]):
                ends.append(i + 1)
        elif ch == ';' and depth == 0:
            ends.append(i + 1)
        i += 1
    at = opening + 1
    while True:
        decl = _DECL.match(clean, at)
        if not decl or re.match(r'\s*(\w+)', clean[at:]).group(1) in _KEYWORDS:
            break
        if re.match(r'\s*\w+\s*=', clean[at:]):
            break
        at = decl.end()
    decl_end = at
    return ends, decl_end


def _pointer_type(clean, opening, closing, var, params):
    for text in (clean[opening:closing], params):
        hit = re.search(rf'((?:(?:unsigned|signed|const)\s+)*[A-Za-z_]\w*)\s*\*\s*{re.escape(var)}\s*[;,=)]', text)
        if hit and hit.group(1) not in _KEYWORDS:
            return hit.group(1)
    return None


def _fresh(clean, base='sb'):
    name, n = base, 0
    while re.search(rf'\b{name}\b', clean):
        n += 1
        name = f'{base}{n}'
    return name


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening, part.end
    params = clean[clean.rfind('(', 0, lo):lo]
    loops = _loops(clean, lo, hi)
    out, seen = [], set()
    for hit in _SUB.finditer(clean, lo, hi):
        ptr, expr = hit.group(1), hit.group(2)
        inside = [loop for loop in loops if loop[1] < hit.start() < loop[2]]
        if not inside:
            continue
        start, body, end = max(inside, key=lambda loop: loop[1])
        text = source[hit.start():hit.end()]
        key = (start, re.sub(r'\s+', '', text))
        if key in seen:
            continue
        seen.add(key)
        names = {ptr} | set(re.findall(_IDENT, expr))
        if any(_writes(clean[start:end], n) for n in names):
            continue
        ptype = _pointer_type(clean, lo, hi, ptr, params)
        if not ptype:
            continue
        opening = _open_of(clean, start, lo)
        if opening is None:
            continue
        closing = _close(clean, opening)
        ends, decl_end = _statements(clean, opening, closing)
        before = [e for e in ends if decl_end < e <= start]
        first = decl_end
        prev = decl_end
        for e in before:
            if any(_writes(clean[prev:e], n) for n in names):
                first = e
            prev = e
        points = [first] + [e for e in before if e > first]
        line = clean.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:]).group(0)
        var = _fresh(clean)
        sub = re.compile(r'\(\s*' + re.escape(ptr) + r'\s*\+\s*' + re.escape(expr) + r'\s*\)\s*\[')
        loop_text = source[start:end]
        renamed = sub.sub(var + '[', loop_text)
        decl = f'\n{indent}{ptype} *{var};'
        for point in points:
            setter = f'\n{indent}{var} = {ptr} + {expr};'
            if point == decl_end:
                edits = [(decl_end, decl_end, decl + setter), (start, end, renamed)]
            else:
                edits = [(decl_end, decl_end, decl), (point, point, setter), (start, end, renamed)]
            out.append((FAMILY, edit(source, edits)))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
