"""Casted byte offsets off a global, written as the typed table or record array the game declared there.

m2c, and the sources searches start from it, reach globals through casts of byte arithmetic:

    extern char D_80200000[];                            extern u16 D_80200000[];
    extern char D_80300000[];                  ->        typedef struct { u16 m0; char pad2[6]; u16 m8; ... } CastRow;
    off = i * 2;                                         extern CastRow D_80302108[];
    v0 = i * 4;                                          D_80302108[i].m0 = D_80200000[i];
    t = (v0 + i) * 8;
    *(u16 *)(D_80300000 + 0x2108 + t) = *(u16 *)(D_80200000 + off);

GCC addresses the two differently: a declared array's index is computed afresh at each access, and an offset known at
compile time goes into the symbol. The offset locals are resolved to the counter's multiple first (a loop that carries
part of the product in a local of its own, `v0 = i * 4` before `(v0 + i) * 8`, reads back as `i * 0x28`), and the
assignments left without a reader are removed.

A 257-instruction N64 record builder under KMC `-O1` was 29545 with its records as casts and exact with them declared;
its machine draft reached 0 from this rewrite, `compare_tree_default_switch` and three register repairs.

Only symbols the source declares as byte arrays are rewritten, when every use of them is such an access with one size
per offset and one stride. Offered with the records at their own address and as a padded record at the symbol.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'cast_offset_records'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4}
_DECLARATION = re.compile(r'^[ \t]*extern[ \t]+(?:signed[ \t]+|unsigned[ \t]+)?(?:char|s8|u8)[ \t]+(' + IDENT
                          + r')[ \t]*\[[ \t]*\][ \t]*;[ \t]*\n', re.M)
_ACCESS = re.compile(r'(?<![\w)\]])\*\s*(?P<wrap>\(\s*)?\(\s*(?P<type>' + '|'.join(SIZES) + r')\s*\*\s*\)\s*\(')
_ADDRESS_NAME = re.compile(r'D_([0-9A-F]{8})')
_TOKEN = re.compile(r'\s*(0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*|<<|[-+*()&])[uUlL]*')
_BYTE_CAST = re.compile(r'\(\s*(?:char|s8|u8)\s*\*\s*\)')
TAG = 'CastRow'


class _Linear:
    """An integer expression as {name: coefficient}, '' for the constant, locals read back through `definitions`."""

    def __init__(self, text, definitions, seen=()):
        self.tokens, at, text = [], 0, text.strip()
        while at < len(text):
            found = _TOKEN.match(text, at)
            if not found:
                raise ValueError(text)
            self.tokens.append(found[1])
            at = found.end()
        self.at, self.definitions, self.seen = 0, definitions, seen

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else ''

    def take(self):
        token = self.peek()
        self.at += 1
        return token

    def value(self):
        form = self.shift()
        if self.at != len(self.tokens):
            raise ValueError('trailing')
        return form

    def shift(self):
        form = self.add()
        while self.peek() == '<<':
            self.take()
            form = _scale(form, 1 << _constant(self.add()))
        return form

    def add(self):
        form = self.mul()
        while self.peek() in ('+', '-'):
            sign = 1 if self.take() == '+' else -1
            for name, k in self.mul().items():
                form[name] = form.get(name, 0) + sign * k
        return {name: k for name, k in form.items() if k}

    def mul(self):
        form = self.atom()
        while self.peek() == '*':
            self.take()
            other = self.atom()
            if set(other) <= {''}:
                form = _scale(form, other.get('', 0))
            else:
                form = _scale(other, _constant(form))
        return form

    def atom(self):
        token = self.take()
        if token == '(':
            if self.peek() in SIZES and self.at + 1 < len(self.tokens) and self.tokens[self.at + 1] == ')':
                self.at += 2  # a cast of an integer to an integer
                return self.atom()
            form = self.shift()
            if self.take() != ')':
                raise ValueError('unclosed')
            return form
        if token[:1].isdigit():
            number = int(token, 0)
            return {'': number} if number else {}
        if not re.fullmatch(IDENT, token):
            raise ValueError(token)
        if token in self.definitions and token not in self.seen:
            forms = []
            for text in self.definitions[token]:
                try:
                    forms.append(_Linear(text, self.definitions, (*self.seen, token)).value())
                except ValueError:
                    return {token: 1}
            # `v = 0 * 4;` before a loop is the same product at the counter's start
            kept = [form for form in forms if form]
            if kept and all(form == kept[0] for form in kept) and token not in kept[0]:
                return dict(kept[0])
        return {token: 1}


def _scale(form, k):
    return {name: value * k for name, value in form.items() if value * k}


def _constant(form):
    if not set(form) <= {''}:
        raise ValueError('not a constant')
    return form.get('', 0)


def _definitions(body):
    """{local: [right-hand sides]} for locals only ever set by plain assignments."""
    found = {}
    for match in re.finditer(r'(?<![\w.>\]*])(' + IDENT + r')\s*=(?!=)\s*([^;{}=]+);', body):
        found.setdefault(match[1], []).append(match[2])
    for name in list(found):
        if re.search(r'(?:\+\+|--)\s*' + name + r'\b|\b' + name + r'\s*(?:\+\+|--|[-+*/|&^]=|<<=|>>=)|&\s*' + name + r'\b',
                     body):
            del found[name]
    return found


def _accesses(clean, source, start, end, symbols, definitions):
    """{symbol: [(span, type, offset, {name: coefficient})]} and the symbols some access of which was not read."""
    out, refused = {}, set()
    for found in _ACCESS.finditer(clean, start, end):
        inner_end = close(clean, found.end() - 1)
        if not inner_end:
            continue
        stop = inner_end
        if found['wrap']:
            rest = re.compile(r'\s*\)').match(clean, inner_end)
            if not rest:
                continue
            stop = rest.end()
        expression = source[found.end():inner_end - 1]
        used = [s for s in symbols if re.search(r'\b' + s + r'\b', expression)]
        if not used:
            continue
        symbol = used[0]
        # `(T *)(X + K) + index` would scale by T: only a parenthesised whole expression is read
        if len(used) != 1 or len(re.findall(r'\b' + symbol + r'\b', expression)) != 1:
            refused.update(used)
            continue
        plain = _BYTE_CAST.sub('', expression).replace('&', ' ') if re.search(r'&\s*' + symbol, expression) else expression
        try:
            form = _Linear(plain, definitions).value()
        except ValueError:
            refused.add(symbol)
            continue
        if form.pop(symbol, 0) != 1:
            refused.add(symbol)
            continue
        offset = form.pop('', 0)
        out.setdefault(symbol, []).append(((found.start(), stop), found['type'], offset, form))
    return out, refused


def _index(form, size):
    """`form / size` written as an expression, or None."""
    if not form or any(k % size for k in form.values()):
        return None
    terms = [name if k == size else f'{name} * {k // size}' for name, k in sorted(form.items())]
    return ' + '.join(terms)


def _plan(symbol, uses, header, source):
    """[(declarations, {span: text})] for one symbol: the ways to declare it."""
    base = min(offset for _, _, offset, _ in uses)
    members = {}
    for _, kind, offset, _ in uses:
        if members.setdefault(offset - base, kind) != kind:
            return []
    scales = {tuple(sorted(form.values())) for _, _, _, form in uses}
    if len(scales) != 1 or len(next(iter(scales))) != 1:
        return []
    stride = next(iter(scales))[0]
    if stride <= 0:
        return []
    if len(members) == 1:
        kind = members[0]
        size = SIZES[kind]
        if stride != size or base % size or base < 0:
            return []
        texts = {}
        for span, _, offset, form in uses:
            index = _index(form, size)
            texts[span] = f'{symbol}[{index}]' if not base else f'{symbol}[({index}) + {base // size}]'
        return [(f'extern {kind} {symbol}[];\n', texts, '')]
    ordered = sorted((at, kind) for at, kind in members.items())
    at = 0
    lines = []
    for offset, kind in ordered:
        size = SIZES[kind]
        if offset < at or offset % size or offset + size > stride:
            return []
        if offset > at:
            lines.append(f'    char pad{at:X}[{offset - at:#x}];')
        lines.append(f'    {kind} m{offset:X};')
        at = offset + size
    if stride > at:
        lines.append(f'    char pad{at:X}[{stride - at:#x}];')
    indices = {span: _index(form, stride) for span, _, _, form in uses}
    if None in indices.values():
        return []
    tag = f'{TAG}_{symbol}'
    if re.search(r'\b' + tag + r'\b', source + header):
        return []
    record = 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\n'
    out = []
    address = _ADDRESS_NAME.fullmatch(symbol)
    if address and base:
        rows = f'D_{int(address[1], 16) + base:08X}'
        if not re.search(r'\b' + rows + r'\b', source + header):
            out.append((record + f'extern {tag} {rows}[];\n',
                        {span: f'{rows}[{indices[span]}].m{offset - base:X}' for span, _, offset, _ in uses}, record))
    if base >= 0:
        pad = f'    char pad[{base:#x}];\n' if base else ''
        whole = f'typedef struct {{\n{pad}    {tag} rows[1];\n}} {tag}Table;\n'
        out.append((record + whole + f'extern {tag}Table {symbol};\n',
                    {span: f'{symbol}.rows[{indices[span]}].m{offset - base:X}' for span, _, offset, _ in uses}, record))
    return out


def _drop_unread(source, name, candidates):
    """`source` without the assignments to, and declarations of, the locals nothing reads any more."""
    changed = True
    while changed:
        changed = False
        for local in sorted(candidates):
            span = find(source, name)
            body = source[span[0]:span[1]]
            clean = _blank(body)
            assignments = list(re.finditer(r'(?<![\w.>])' + local + r'\s*=(?!=)[^;{}]*;', clean))
            if not assignments:
                continue
            rest = clean
            for match in reversed(assignments):
                rest = rest[:match.start()] + rest[match.end():]
            rest = re.sub(r'\b(?:s8|u8|s16|u16|s32|u32|int|short|char)\s+' + local + r'\s*;', '', rest)
            if re.search(r'\b' + local + r'\b', rest):
                continue
            for match in reversed(assignments):
                body = body[:match.start()] + body[match.end():]
            body = re.sub(r'\n[ \t]*(?:s8|u8|s16|u16|s32|u32|int|short|char)[ \t]+' + local + r'[ \t]*;', '', body)
            body = re.sub(r'\n[ \t]+(?=\n)', '', body)
            source = source[:span[0]] + body + source[span[1]:]
            changed = True
    return source


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    head = _blank(source[:span[0]])
    symbols = [m[1] for m in _DECLARATION.finditer(head) if not re.search(r'\b' + m[1] + r'\b', _blank(header))]
    if not symbols:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    definitions = _definitions(clean[opening:span[1]])
    uses, refused = _accesses(clean, source, opening, span[1], symbols, definitions)
    plans = {}
    for symbol, found in uses.items():
        if symbol in refused or len(re.findall(r'\b' + symbol + r'\b', clean[opening:span[1]])) != len(found):
            continue
        ways = _plan(symbol, found, header, source)
        if ways:
            plans[symbol] = ways
    if not plans:
        return []
    read = set()
    for symbol in plans:
        for (a, b), *_ in uses[symbol]:
            read.update(name_ for name_ in re.findall(IDENT, clean[a:b]) if name_ in definitions)
    # the locals those were computed from
    for _ in range(3):
        for local in list(read):
            for text in definitions[local]:
                read.update(n for n in re.findall(IDENT, text) if n in definitions)

    def build(choice):
        edits, declarations = [], {}
        for symbol, ways in plans.items():
            way = ways[min(choice, len(ways) - 1)]
            declarations[symbol] = way[0]
            edits += list(way[1].items())
        text = source
        for (a, b), replacement in sorted(edits, reverse=True):
            text = text[:a] + replacement + text[b:]
        for symbol, declaration in declarations.items():
            text = re.sub(r'^[ \t]*extern[ \t]+(?:signed[ \t]+|unsigned[ \t]+)?(?:char|s8|u8)[ \t]+' + symbol
                          + r'[ \t]*\[[ \t]*\][ \t]*;[ \t]*\n', lambda _, d=declaration: d, text, count=1, flags=re.M)
        return _drop_unread(text, name, read)

    out = []
    for choice in range(max(len(ways) for ways in plans.values())):
        text = build(choice)
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    from . import compare_tree_default_switch
    for family, text in list(out)[:1]:
        # the pair that only pays off together on a draft: the typed records and the `switch` around their arms
        for _, child in compare_tree_default_switch.variants(text, name)[:1]:  # (the arms' result store sunk, when it has one)
            out.append((family, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
