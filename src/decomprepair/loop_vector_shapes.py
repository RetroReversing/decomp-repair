"""Loop and vector-update shapes that decide KMC gcc 2.7.2's scheduling over whole loop bodies.

Measured on an N64 skeletal-animation function of 2,122 instructions (gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2)
whose structure already matched: each of these, undone one at a time from the exact source, cost the listed number
of differing instructions.

- `indexed_pointer_loop` (100): a loop that walks a pointer beside its counter, `for (k = 0, p = base; p->f >= 0;
  k++, p++)`, keeps a second induction register; the original indexed, `for (k = 0; base[k].f >= 0; k++) { p =
  &base[k];`, and recomputed the element from the counter.
- `const_walked_pointer` (50): a local pointer only read through, written `const T *`. The scheduler may then move
  its loads across the stores of the loop body (into a temporary filled while earlier sums are still stored);
  through a plain pointer every load waits for the stores before it.
- `vector_update_temps` (36 and 18 at two sites): three compound updates of one vector's components, `v.x += a;
  v.y += b; v.z += c;`, store each sum before the next load. The original computed all three sums into temporaries
  first and stored them after (a `VSET(v, x, y, z)` style macro), so the loads were grouped and the stores came
  last.

All three change no behaviour: the indexed loop reads the same element, `const` only forbids writes the function
never makes, and the temporaries are read before any of the stores, which only matters when the components overlap
the operands (they are rejected when an operand names the vector). Propose only; the judge decides.
"""
import re

from .csource import _blank, find

FAMILIES = ('indexed_pointer_loop', 'const_walked_pointer', 'vector_update_temps')

_ID = r'[A-Za-z_]\w*'
_WALK = re.compile(
    rf'for\s*\(\s*({_ID})\s*=\s*0\s*,\s*({_ID})\s*=\s*({_ID})\s*;'
    rf'([^;{{}}]*);\s*(?:\1\s*\+\+\s*,\s*\2\s*\+\+|\2\s*\+\+\s*,\s*\1\s*\+\+)\s*\)\s*\{{')
_DECL = re.compile(rf'(?m)^([ \t]*)((?!const\b|return\b|struct\b(?=\s*{{))(?:struct\s+)?{_ID})\s*\*\s*({_ID})\s*;')
_UPDATE = re.compile(rf'(?m)^([ \t]*)([^;\n{{}}=]*?)\.({_ID})\s*([-+*])=\s*([^;\n]+);[ \t]*$')
_CALLS = re.compile(rf'\b({_ID})\s*\(')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return None
    return span, clean, opening


def _indexed_loops(source, clean, opening, end):
    out = []
    for m in _WALK.finditer(clean, opening, end):
        k, p, base, cond = m[1], m[2], m[3], m[4]
        if p == base or k in (p, base) or not re.search(rf'\b{p}\b', cond):
            continue
        # the walked pointer must not be advanced or reassigned inside the body: the indexed form recomputes it
        close = _matching(clean, m.end() - 1)
        if close < 0 or re.search(rf'\b{p}\s*(?:\+\+|--|[-+]?=(?!=))|(?:\+\+|--)\s*{p}\b', clean[m.end():close]):
            continue
        element = f'{base}[{k}]'
        new_cond = re.sub(rf'\b{p}\s*->', f'{element}.', cond)
        new_cond = re.sub(rf'\b{p}\b', f'(&{element})', new_cond)
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, m.start()) + 1:]).group(0)
        head = f'for ({k} = 0;{new_cond}; {k}++) {{\n{indent}    {p} = &{element};'
        out.append(('indexed_pointer_loop', source[:m.start()] + head + source[m.end():]))
    return out


def _matching(clean, at):
    depth = 0
    for i in range(at, len(clean)):
        if clean[i] == '{':
            depth += 1
        elif clean[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _only_read(body, var):
    """True when the function never writes through `var` nor hands it to a call (a callee could write)."""
    through = rf'(?:\b{var}\s*->\s*{_ID}(?:\s*\.\s*{_ID}|\s*\[[^\]]*\])*|\*\s*{var}\b|\b{var}\s*\[[^\]]*\])'
    if re.search(through + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body) or re.search(through + r'\s*(?:\+\+|--)', body) \
            or re.search(r'(?:\+\+|--)\s*' + through, body):
        return False
    if re.search(rf'&\s*{var}\s*->', body):  # an address taken from it may be written later
        return False
    for call in _CALLS.finditer(body):
        if call[1] in _KEYWORDS:
            continue
        depth, i = 1, call.end()
        while i < len(body) and depth:
            depth += {'(': 1, ')': -1}.get(body[i], 0)
            i += 1
        # a value read through it (`f(p->x)`) is still a read; the pointer itself handed over could be written
        args = re.sub(rf'\b{var}\s*->\s*{_ID}(?:\s*\.\s*{_ID})*(?!\s*[\[(])', 'v_', body[call.end():i - 1])
        if re.search(rf'\b{var}\b', args):
            return False
    return bool(re.search(rf'\b{var}\s*->|\b{var}\s*\[', body))


def _const_pointers(source, clean, opening, end):
    body = clean[opening:end]
    names = []
    for m in _DECL.finditer(clean, opening, end):
        if _only_read(body, m[3]):
            names.append(m)
    def marked(group):
        text = source
        for m in sorted(group, key=lambda m: m.start(2), reverse=True):
            text = text[:m.start(2)] + 'const ' + text[m.start(2):]
        return text

    out = []
    # A table and the pointers walking it share one element type and go `const` together (in the measured
    # function, `const` on the unrelated frame pointers cost 3 instructions while the table's gained 50).
    by_type = {}
    for m in names:
        by_type.setdefault(m[2], []).append(m)
    for group in by_type.values():
        if 1 < len(group) < len(names):
            out.append(('const_walked_pointer', marked(group)))
    for m in names:
        out.append(('const_walked_pointer', source[:m.start(2)] + 'const ' + source[m.start(2):]))
    if len(names) > 1:
        text = source
        for m in reversed(names):
            text = text[:m.start(2)] + 'const ' + text[m.start(2):]
        out.append(('const_walked_pointer', text))
    return out


def _vector_updates(source, clean, opening, end):
    out = []
    lines = list(_UPDATE.finditer(clean, opening, end))
    for a, b, c in zip(lines, lines[1:], lines[2:]):
        group = (a, b, c)
        if any(clean[x.end():y.start()] != '\n' for x, y in ((a, b), (b, c))):
            continue
        target = a[2].strip()
        if not target or any(x[2].strip() != target or x[4] != a[4] for x in group):
            continue
        fields = [x[3] for x in group]
        if len(set(fields)) != 3 or re.search(r'\+\+|--|\(', target):
            continue
        root = re.match(_ID, target)
        operands = [source[x.start(5):x.end(5)].strip() for x in group]
        # a temporary read after a store would change behaviour if an operand reads the vector itself
        if root and any(re.search(rf'\b{root.group(0)}\b', o) for o in operands):
            continue
        indent, op = a[1], a[4]
        names = ('vx_', 'vy_', 'vz_')
        lhs = [f'{source[x.start(2):x.end(2)].strip()}.{x[3]}' for x in group]
        sums = '\n'.join(f'{indent}    __typeof__({l}) {n} = {l} {op} ({o});' for l, n, o in zip(lhs, names, operands))
        stores = '\n'.join(f'{indent}    {l} = {n};' for l, n in zip(lhs, names))
        block = f'{indent}{{\n{sums}\n{stores}\n{indent}}}'
        out.append(('vector_update_temps', source[:a.start()] + block + source[c.end():]))
        # the operands computed before any of the sums (the original's helper took them as arguments)
        terms = '\n'.join(f'{indent}    __typeof__({l}) {n}t = {o};' for l, n, o in zip(lhs, names, operands))
        sums2 = '\n'.join(f'{indent}    __typeof__({l}) {n} = {l} {op} {n}t;' for l, n in zip(lhs, names))
        block2 = f'{indent}{{\n{terms}\n{sums2}\n{stores}\n{indent}}}'
        out.append(('vector_update_temps', source[:a.start()] + block2 + source[c.end():]))
    return out


def variants(source, name, arch='mips', asm='', header=''):
    """Proposals for `name`, best-evidenced families first. MIPS only: the measurements are KMC gcc's."""
    if arch != 'mips':
        return []
    found = _body(source, name)
    if not found:
        return []
    span, clean, opening = found
    end = span[1]
    if re.search(r'\bvolatile\b', clean[opening:end]):
        return []
    result = _indexed_loops(source, clean, opening, end)
    result += _const_pointers(source, clean, opening, end)
    result += _vector_updates(source, clean, opening, end)
    return result[:24]
