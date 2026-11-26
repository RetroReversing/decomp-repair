"""Byte tables walked by address arithmetic, written back as the arrays and records the game declared.

m2c, and every search that starts from its draft, reads a global it knows nothing about as `extern u8 D_80100000[];`
and spells each access as a sum of scaled indices: `D[row * 0x110 + k * 0x22]`, `*(u16 *) (D2 + row * 0xE0 + k * 0x10
+ j * 2)`, row pointers (`out = D3 + row * 14; ... out[k]`) and a base pointer read at fixed offsets (`base = D4;
... base[i + 0x14]`, `*(s32 *) (base + i * 4 + 0x11C)`). The game wrote `u8 D[][8][0x22]`, `u16 D2[][14][8]` and
one structure for `D4`. On an 80-instruction KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O1`) table loader the
difference was the whole near-miss: as arrays the loop pass hoists each row address where the target has it and the
loop counters take the target's registers (the saved plateau went 1775 -> 265 with the three tables as arrays, and 0
with the source table also a structure). The edits only pay off together, so one child rewrites every table at once,
then one child per table. The explanation of the registers is a hypothesis; the exact judge decides.

linear_subscript_view
    A table: a `u8`/`s8`/`char` array the candidate declares itself whose every use is an access at a sum of scaled
    indices with no constant part and one element type: declared with that element type and one dimension per
    stride (an element stride wider than the type gets a last dimension of its own, indexed `[0]`). A record: such an
    array read at constant offsets (directly or through a pointer that only ever holds its address): one structure
    with a member per offset, each an array shaped by its strides, padding between. Row pointers set once from a
    table plus indices are read through and removed.

The program reads and writes the same addresses. A table with a use the rewrite cannot read (its address passed on,
a stepped pointer, an index written between a row pointer's assignment and a read through it) is left alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'linear_subscript_view'
FAMILIES = (FAMILY,)
LIMIT = 6

_SIZES = {'u8': 1, 's8': 1, 'char': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4, 'int': 4, 'float': 4,
          'u64': 8, 's64': 8, 'f64': 8}
_BYTE = r'(?:unsigned\s+char|signed\s+char|u8|s8|char)'


class _Unknown(Exception):
    pass


def _closing(text, at):
    """The index of the bracket that closes the one at `at`."""
    pair = {'(': ')', '[': ']'}[text[at]]
    end = close(text, at, text[at], pair)
    if end is None:
        raise _Unknown
    return end - 1


def _split_sum(text):
    """The top-level `+` terms of an expression."""
    terms, depth, last = [], 0, 0
    for i, c in enumerate(text):
        depth += (c in '([') - (c in ')]')
        if depth == 0 and c == '+':
            if text[i - 1:i] == '+' or text[i + 1:i + 2] in ('+', '='):
                raise _Unknown
            terms.append(text[last:i])
            last = i + 1
    terms.append(text[last:])
    return terms


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and _closing(text, 0) == len(text) - 1:
        text = text[1:-1].strip()
    return text


def _number(text):
    text = _unwrap(text)
    if re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?', text):
        return int(text.rstrip('uU'), 0)
    return None


def _linear(text, roots):
    """(root or None, {index expression: stride}, constant) of an address expression."""
    root, terms, constant = None, {}, 0
    text = _unwrap(text)
    cast = re.match(rf'\(\s*{_BYTE}\s*\*\s*\)', text)
    if cast:
        text = _unwrap(text[cast.end():])
    parts = _split_sum(text)
    if len(parts) > 1:
        for part in parts:
            r, t, c = _linear(part, roots)
            if r:
                if root:
                    raise _Unknown
                root = r
            for key, stride in t.items():
                if key in terms:
                    raise _Unknown
                terms[key] = stride
            constant += c
        return root, terms, constant
    value = _number(text)
    if value is not None:
        return None, {}, value
    if text in roots:
        return text, {}, 0
    # `index * K` or `index << K` (the whole term)
    depth = 0
    for i, c in enumerate(text):
        depth += (c in '([') - (c in ')]')
        if depth:
            continue
        if c == '*' and text[:i].strip():
            scale = _number(text[i + 1:])
            if scale:
                return None, {_unwrap(text[:i]): scale}, 0
        if text.startswith('<<', i):
            shift = _number(text[i + 2:])
            if shift is not None:
                return None, {_unwrap(text[:i]): 1 << shift}, 0
    # anything else is one index; it must not hide a root or subtract
    depth = 0
    for i, c in enumerate(text):
        depth += (c in '([') - (c in ')]')
        if depth == 0 and c in '-+*/' and i and text[i - 1] not in '(&' and text[i:i + 2] != '->':
            raise _Unknown
    if any(re.search(rf'\b{re.escape(r)}\b', text) for r in roots):
        raise _Unknown
    return None, {text: 1}, 0


class _Access:
    def __init__(self, start, end, root, via, terms, constant, kind):
        self.start, self.end, self.root, self.via = start, end, root, via
        self.terms, self.constant, self.kind = terms, constant, kind


def _depth_end(body, at):
    """Where the block holding position `at` closes."""
    depth = 0
    for brace in re.compile(r'[{}]').finditer(body, at):
        depth += 1 if brace.group() == '{' else -1
        if depth < 0:
            return brace.start()
    return len(body)


def _pointers(body, roots):
    """{pointer: (root, terms, constant, element type, declaration spans, assignment span)} for byte pointers set once."""
    out = {}
    for decl in re.finditer(rf'(?m)^[ \t]*({_BYTE})\s*\*\s*([A-Za-z_]\w*)\s*;[ \t]*\n?', body):
        kind, name = decl.group(1), decl.group(2)
        writes = list(re.finditer(rf'(?<![\w.>]){name}\s*(?:=(?!=)|\+=|-=|\+\+|--)|(?:\+\+|--|&)\s*{name}\b(?!\s*\[)', body))
        if len(writes) != 1 or not writes[0].group().endswith('='):
            continue
        stmt = re.compile(rf'(?m)^[ \t]*{name}\s*=\s*([^;{{}}]+);[ \t]*\n?').search(body)
        if not stmt:
            continue
        out[name] = [stmt.group(1), kind, decl.span(), stmt.span()]
    resolved = {}

    def resolve(name, seen=()):
        if name in resolved:
            return resolved[name]
        if name in seen:
            raise _Unknown
        text = out[name][0]
        root, terms, constant = _linear(text, set(roots) | set(out))
        if root in out:
            base = resolve(root, seen + (name,))
            if set(base[1]) & set(terms):
                raise _Unknown
            root, terms, constant = base[0], {**base[1], **terms}, base[2] + constant
        if root is None:
            raise _Unknown
        resolved[name] = (root, terms, constant, out[name][1], out[name][2], out[name][3])
        return resolved[name]

    for name in out:
        try:
            resolve(name)
        except _Unknown:
            pass
    return resolved


def _stable(body, pointers, name, use):
    """A row pointer's indices are not written between its assignment and the read, which its block reaches."""
    _, terms, _, _, _, stmt = pointers[name]
    if use < stmt[1] or use > _depth_end(body, stmt[1]):
        return False
    between = body[stmt[1]:use]
    for term in terms:
        for word in set(re.findall(r'(?<![\w.>])[A-Za-z_]\w*', term)):
            if word in _SIZES:
                continue
            if re.search(rf'(?<![\w.>]){word}\s*(?:[-+*/&|^]?=(?!=)|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{word}\b', between):
                return False
    return True


def _accesses(body, roots):
    """Every access through `roots` (and pointers made from them), or None per root when one cannot be read."""
    pointers = _pointers(body, roots)
    bases = {n: p for n, p in pointers.items() if not p[1] and not p[2]}   # holds the table's address itself
    rows = {n: p for n, p in pointers.items() if n not in bases}
    names = set(roots) | set(pointers)
    found, claimed = [], []
    covered = [p[4] for p in rows.values()] + [p[5] for p in rows.values()]

    def inside(at, spans):
        return any(a <= at < b for a, b in spans)

    def add(start, end, text, kind, index=None):
        try:
            root, terms, constant = _linear(text, names)
            if root is None:
                return
            if index is not None:
                other, more, extra = _linear(index, names)
                if other or set(more) & set(terms):
                    raise _Unknown
                size = _SIZES[kind]
                terms = {**terms, **{k: v * size for k, v in more.items()}}
                constant += extra * size
            via = None
            if root in pointers:
                via = root
                p = pointers[root]
                if root in rows and (set(p[1]) & set(terms) or not _stable(body, pointers, root, start)):
                    raise _Unknown
                root, terms, constant = p[0], {**p[1], **terms}, p[2] + constant
            found.append(_Access(start, end, root, via, terms, constant, kind))
            claimed.append((start, end))
        except _Unknown:
            return

    for m in re.finditer(r'\*\s*\(\s*([A-Za-z_]\w*)\s*\*\s*\)\s*(?=[A-Za-z_(])', body):
        kind = m.group(1)
        if kind not in _SIZES or inside(m.start(), covered):
            continue
        if body[m.end()] == '(':
            end = _closing(body, m.end()) + 1
            text = body[m.end() + 1:end - 1]
        else:
            word = re.match(r'[A-Za-z_]\w*', body[m.end():]).group()
            end, text = m.end() + len(word), word
        add(m.start(), end, text, kind)
    for m in re.finditer(r'(?<![\w.>])([A-Za-z_]\w*)\s*\[', body):
        name = m.group(1)
        if name not in names or inside(m.start(), covered + claimed):
            continue
        end = _closing(body, m.end() - 1) + 1
        if body[end:].lstrip().startswith(('[', '.', '->')) or body[:m.start()].rstrip().endswith('&'):
            continue
        kind = pointers[name][3] if name in pointers else roots[name]
        add(m.start(), end, name, kind, body[m.end():end - 1])
    # every other mention of a table or its pointers must be an assignment or declaration this rewrite replaces
    allowed = covered + claimed
    for name, p in bases.items():
        allowed += [p[4], p[5]]
    broken = set()
    for name in names:
        root = pointers[name][0] if name in pointers else name
        for m in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', body):
            if not inside(m.start(), allowed):
                broken.add(root)
    return found, pointers, bases, broken


def _shape(strides, size):
    """The inner dimensions for strides (largest first) over elements of `size`, and whether a last `[0]` is needed."""
    for a, b in zip(strides, strides[1:]):
        if a % b:
            raise _Unknown
    if strides[-1] % size:
        raise _Unknown
    dims = [a // b for a, b in zip(strides, strides[1:])]
    pad = strides[-1] // size
    return (dims + [pad], True) if pad > 1 else (dims, False)


def _strides(accesses):
    """The member's strides, largest first; each stride belongs to at most one index in each access."""
    strides = set()
    for a in accesses:
        if len(set(a.terms.values())) != len(a.terms):
            raise _Unknown
        strides |= set(a.terms.values())
    return sorted(strides, reverse=True)


def _subscripts(access, strides, extra):
    index = {stride: key for key, stride in access.terms.items()}
    return ''.join(f'[{index.get(s, "0")}]' for s in strides) + ('[0]' if extra else '')


def _plan(name, accesses, pointers, bases):
    """(new extern declaration, [typedef], {access: replacement}, pointer type or None) for one table."""
    offsets = {}
    for a in accesses:
        offsets.setdefault(a.constant, []).append(a)
    aliases = [n for n, p in bases.items() if p[0] == name]
    if set(offsets) == {0} and not aliases:
        kinds = {a.kind for a in accesses}
        if len(kinds) != 1:
            raise _Unknown
        kind = kinds.pop()
        strides = _strides(accesses)
        if not strides:
            raise _Unknown
        dims, extra = _shape(strides, _SIZES[kind])
        declaration = f'extern {kind} {name}[]' + ''.join(f'[{d}]' for d in dims) + ';'
        return declaration, [], {a: name + _subscripts(a, strides, extra) for a in accesses}, None
    if min(offsets) < 0:
        raise _Unknown
    view = f'View_{name}'
    lines, replace, at = [], {}, 0
    ordered = sorted(offsets)
    for position, offset in enumerate(ordered):
        group = offsets[offset]
        kinds = {a.kind for a in group}
        if len(kinds) != 1 or offset < at or offset % _SIZES[next(iter(kinds))]:
            raise _Unknown
        kind = kinds.pop()
        size = _SIZES[kind]
        if offset > at:
            lines.append(f'    u8 pad{at:X}[0x{offset - at:X}];')
        strides = _strides(group)
        gap = ordered[position + 1] - offset if position + 1 < len(ordered) else None
        dims, extra = [], False
        if strides:
            dims, extra = _shape(strides, size)
            row = strides[0]
            count = gap // row if gap is not None else 16
            if count < 1:
                raise _Unknown
            dims = [count] + dims
        total = size
        for d in dims:
            total *= d
        lines.append(f'    {kind} m{offset:X}' + ''.join(f'[{d}]' for d in dims) + ';')
        at = offset + total
        for a in group:
            owner = a.via if a.via in bases else (aliases[0] if len(aliases) == 1 and a.via else None)
            owner = owner or f'(({view} *) {name})'
            replace[a] = f'{owner}->m{offset:X}' + (_subscripts(a, strides, extra) if strides else '')
    typedef = 'typedef struct\n{\n' + '\n'.join(lines) + f'\n}} {view};\n'
    return None, [typedef], replace, view


def _apply(source, span, chosen, plans, pointers, bases, declarations):
    start, end = span
    body = source[start:end]
    edits = []
    for name in chosen:
        _, _, replace, view = plans[name]
        for access, text in replace.items():
            # an index may itself hold a rewritten read; those are left to the child that rewrites one table
            edits.append((access.start, access.end, text))
        for pointer, p in pointers.items():
            if p[0] != name:
                continue
            if pointer in bases:
                value = re.compile(rf'({pointer}\s*=\s*)[^;]+;').search(body, p[5][0])
                edits.append((value.start(), value.end(), f'{value.group(1)}({view} *) {name};'))
                declared = re.compile(rf'{_BYTE}(\s*\*\s*){pointer}\s*;').search(body, p[4][0])
                edits.append((declared.start(), declared.end(), f'{view}{declared.group(1)}{pointer};'))
            else:
                edits.append((*p[4], ''))
                edits.append((*p[5], ''))
    edits.sort()
    for a, b in zip(edits, edits[1:]):
        if b[0] < a[1]:
            return None
    for a, b, text in reversed(edits):
        body = body[:a] + text + body[b:]
    head = source[:start]
    tail = source[end:]
    types = ''
    for name in chosen:
        declaration, typedefs, _, _ = plans[name]
        types += ''.join(typedefs)
        if declaration:
            old = declarations[name]
            head = head.replace(old, declaration, 1)
    line = head.rfind('\n') + 1
    return head[:line] + types + head[line:] + body + tail


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    body = clean[start:end]
    outside = clean[:start] + clean[end:]
    roots, declarations = {}, {}
    for m in re.finditer(rf'(?m)^[ \t]*extern\s+({_BYTE})\s+([A-Za-z_]\w*)\s*\[\s*\]\s*;', clean[:start]):
        root = m.group(2)
        if len(re.findall(rf'\b{root}\b', outside)) == 1 and re.search(rf'\b{root}\b', body):
            roots[root] = m.group(1)
            declarations[root] = source[m.start():m.end()].lstrip()
    if not roots:
        return []
    try:
        found, pointers, bases, broken = _accesses(body, roots)
    except _Unknown:
        return []
    plans = {}
    for root in roots:
        mine = [a for a in found if a.root == root]
        if not mine or root in broken:
            continue
        # a byte table read only at plain indices is already the array the game declared
        if all(a.constant == 0 and a.via is None and set(a.terms.values()) <= {1} and _SIZES[a.kind] == 1 for a in mine):
            continue
        try:
            plans[root] = _plan(root, mine, pointers, bases)
        except _Unknown:
            continue
    if not plans:
        return []
    choices = [list(plans)]
    if len(plans) > 1:
        records = [n for n, p in plans.items() if p[3]]
        if records and len(records) < len(plans):
            choices.append([n for n in plans if n not in records])
        choices += [[n] for n in plans]
    out = []
    for chosen in choices:
        child = _apply(source, span, chosen, plans, pointers, bases, declarations)
        if child and child != source and (FAMILY, child) not in out:
            out.append((FAMILY, child))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
