"""Address-named tables indexed by `i * STRIDE`, written back as the record array the game declared there.

m2c names each field of a global record array by its own address and adds the product to it:

    temp = i * 0x178;                                      f(&D_800DA260[i]);
    f(temp + &D_800DA260);                      ->         D_800DA260[i].m0 = i;
    *(&D_800DA260 + temp) = i;                             D_800DA260[i].m2 = 0;
    *(&D_800DA262 + temp) = 0;                             ...
    inner = (j * 8) + (i * 0x178);                         D_800DA260[i].m28[j].m0 = 0;
    *(&D_800DA26A + 0x1E + inner) = 0;                     D_800DA260[i].m28[j].m4 = 0;

KMC GCC 2.7.2 treats the two differently under `-O1`: with the array declared, one saved register holds `i * STRIDE`
across a call and every member store stays `lui %hi(D+K); addu; sw %lo`; byte arithmetic on separate symbols with a
named temporary does not give those registers. A 114-instruction N64 table initialiser was 1480 at its saved best
after 33 attempts and 1600 at the end of a repair chain from its draft, and is exact with this record array under
`-O1` (the register explanation is a hypothesis from the two compiles).

m2c's unstructured inner loops carry the byte offset of the counter in a temporary of their own; it is written
back as the product first (the loop's `goto`s stay for the goto families):

    i = 0;                                              i = 0;
    off = 0 * 2;                                  ->
    loop: *(off + ((j * 0x70) + &D_801000006)) = *(off + D_80200000);
                                                        D_80100000[j].m6[i].m0 = D_80200000[i];
    i += 1;
    off = i * 2;
    if (i < 16) goto loop;

The record's base is the lowest address read rounded down to the widest member, so each member keeps its address:
a table whose lowest field is a byte at +1 is the record at the word before it (`D_80100000[i].m1`).

A table that no access scales by the record size is another table and stays as it is, as long as it lies outside the
record. A member of a small array that the target names by no `%lo` and the source does not cast takes the width of
its own subscript. Such a 97-instruction N64 initialiser went from a 5200 draft to this form (820, and exact with the
goto loop structured, `-O1`).

Widths come from the target's own loads and stores (`%lo(D_X + K)`), since m2c's draft types the symbols `M2C_UNK`;
an offset the assembly does not name falls back to the access's own cast. A second, smaller index becomes a member
array of records. Nothing is rewritten unless every use of every symbol involved is understood.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'indexed_symbol_records'
FAMILIES = (FAMILY,)
TAG = 'IndexedRow'

_SIZE = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4, 'float': 4}
_SYMBOL = r'D_[0-9A-Fa-f]{8}'
_NUMBER = re.compile(r'(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?')
_BYTE_CAST = re.compile(r'^\(\s*(?:char|s8|u8)\s*\*\s*\)\s*')
_ACCESS = re.compile(r'\*\s*(?:\(\s*(?P<type>[A-Za-z_]\w*)\s*\*\s*\)\s*)?(?=\()|\*\s*\(\s*(?=\(\s*[A-Za-z_]\w*\s*\*)')
_TARGET = re.compile(r'\b(?P<op>sb|sh|sw|lb|lbu|lh|lhu|lw|swc1|lwc1)\s+\$\w+\s*,\s*%lo\(\s*(?P<sym>' + _SYMBOL +
                     r')\s*(?:\+\s*(?P<add>0[xX][0-9A-Fa-f]+|\d+))?\s*\)')
_WIDTH = {'sb': 'u8', 'sh': 's16', 'sw': 's32', 'lb': 's8', 'lbu': 'u8', 'lh': 's16', 'lhu': 'u16', 'lw': 's32',
          'swc1': 'f32', 'lwc1': 'f32'}


def _value(text):
    return int(text.rstrip('uU'), 0)


def _wrapped(text):
    return text.startswith('(') and close(text, 0, '(', ')') == len(text)


def _split(text, operator):
    """`text` split at the top-level `operator` (`+` or `*`); `++` is left alone."""
    parts, depth, last = [], 0, 0
    for found in re.finditer(r'[()\[\]]|\+\+|\+|\*', text):
        token = found[0]
        if token in '([':
            depth += 1
        elif token in ')]':
            depth -= 1
        elif token == operator and not depth:
            parts.append(text[last:found.start()].strip())
            last = found.end()
    return parts + [text[last:].strip()]


def _terms(text, temps, at, seen=()):
    """(symbols, constant, [(index text, scale)]) of the byte address `text`, or None."""
    text = text.strip()
    parts = _split(text, '+')
    if len(parts) > 1:
        symbols, constant, indices = [], 0, []
        for part in parts:
            inner = _terms(part, temps, at, seen)
            if inner is None:
                return None
            symbols += inner[0]
            constant += inner[1]
            indices += inner[2]
        return symbols, constant, indices
    cast = _BYTE_CAST.match(text)
    if cast:
        return _terms(text[cast.end():], temps, at, seen)
    if _wrapped(text):
        return _terms(text[1:-1], temps, at, seen)
    if _NUMBER.fullmatch(text):
        return [], _value(text), []
    symbol = re.fullmatch(r'&?\s*(' + _SYMBOL + r')', text)
    if symbol:
        return [symbol[1]], 0, []
    product = _split(text, '*')
    if len(product) == 2 and _NUMBER.fullmatch(product[1]):
        index = product[0][1:-1].strip() if _wrapped(product[0]) else product[0]
        return [], 0, [(index, _value(product[1]))]
    if text in temps and text not in seen:
        earlier = [value for where, value in temps[text] if where < at]
        if earlier:
            return _terms(earlier[-1], temps, at, seen + (text,))
    return None


def _target_widths(asm):
    widths = {}
    for m in _TARGET.finditer(asm or ''):
        address = int(m['sym'][2:], 16) + (int(m['add'], 0) if m['add'] else 0)
        widths.setdefault(address, set()).add(m['op'])
    return widths


def _type(address, cast, widths):
    ops = widths.get(address)
    if not ops:
        return cast if cast in _SIZE else None
    kinds = {_WIDTH[op] for op in sorted(ops, key=lambda op: op[0] != 'l')[:1]}
    kind = kinds.pop()
    if cast in _SIZE and _SIZE[cast] == _SIZE[kind] and all(op[0] == 's' for op in ops):
        return cast
    return kind


def _offset_temps(text, blank):
    """`text` with the counter's carried byte offsets (`T = N * S;` ... `i += 1; T = i * S;`) written as `(i * S)`."""
    found = []
    for step in re.finditer(r'(?m)\b([A-Za-z_]\w*)[ \t]*\+=[ \t]*1;\s*([A-Za-z_]\w*)[ \t]*=[ \t]*\1[ \t]*\*[ \t]*(\d+);', blank):
        counter, temp, scale = step[1], step[2], step[3]
        writes = list(re.finditer(r'(?m)^[ \t]*' + temp + r'[ \t]*=[ \t]*([^=;]+);[ \t]*\n', blank))
        if len(writes) != 2 or re.search(r'&[ \t]*' + temp + r'\b|\b' + temp + r'[ \t]*(?:\+\+|--|[-+*/|&^]=)', blank):
            continue
        first = re.fullmatch(r'(\d+)[ \t]*\*[ \t]*' + scale, writes[0][1].strip())
        if not first or not writes[0].end() <= step.start():
            continue
        started = re.findall(r'\b' + counter + r'[ \t]*=[ \t]*([^=;]+);', blank[:writes[0].start()])
        if not started or started[-1].strip() != first[1]:
            continue
        found.append((counter, temp, scale))
    for counter, temp, scale in found:
        text = re.sub(r'(?m)^[ \t]*' + temp + r'[ \t]*=[^=;]+;[ \t]*\n', '', text)
        text = re.sub(r'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+' + temp + r'[ \t]*;[ \t]*\n', '', text)
        text = re.sub(r'\b' + temp + r'\b', f'({counter} * {scale})', text)
    return text, found


def _other_tables(text, found, stride):
    """`*((i * S) + D)` of a table the record does not hold, written `D[i]`: `i * S` was a byte offset."""
    for counter, _, scale in found:
        offset = r'\([ \t]*' + counter + r'[ \t]*\*[ \t]*' + scale + r'[ \t]*\)'
        shape = re.compile(r'\*[ \t]*\([ \t]*(?:' + offset + r'[ \t]*\+[ \t]*&?(' + _SYMBOL + r')|&?(' + _SYMBOL +
                           r')[ \t]*\+[ \t]*' + offset + r')[ \t]*\)')
        for m in reversed(list(shape.finditer(text))):
            symbol = m[1] or m[2]
            declared = re.search(r'\bextern[ \t]+([A-Za-z_]\w*)[ \t]+' + symbol + r'\b', text)
            if declared and _SIZE.get(declared[1]) == int(scale) and int(scale) != stride:
                text = text[:m.start()] + f'{symbol}[{counter}]' + text[m.end():]
    return text


def _accesses(body, temps, widths):
    """[(start, end, symbol, address, type, [(index, scale)])] of every dereference of a symbol sum."""
    found = []
    for m in _ACCESS.finditer(body):
        opening = body.find('(', m.end() - 1 if body[m.end() - 1] == '(' else m.end())
        if opening < 0:
            continue
        stop = close(body, opening, '(', ')')
        if not stop:
            continue
        inner, cast = body[opening + 1:stop - 1], m['type']
        # `*((T *) (sum))`: the cast and the sum inside one more pair of parentheses
        nested = re.fullmatch(r'\s*\(\s*([A-Za-z_]\w*)\s*\*\s*\)\s*(\(.*\))\s*', inner, re.S)
        if cast is None and nested and _wrapped(nested[2]):
            cast, inner = nested[1], nested[2][1:-1]
        if not re.search(r'\b' + _SYMBOL + r'\b', inner) and not any(t in temps for t in re.findall(r'\w+', inner)):
            continue
        terms = _terms(inner, temps, m.start())
        if terms is None or len(terms[0]) != 1 or not terms[2]:
            continue
        symbol = terms[0][0]
        address = int(symbol[2:], 16) + terms[1]
        kind = _type(address, cast, widths)
        if kind is None and len(terms[2]) == 2:
            kind = {2: 's16', 4: 's32'}.get(min(scale for _, scale in terms[2]))
        found.append((m.start(), stop, symbol, address, kind, terms[2]))
    return found


def _member_lines(members, total, indent):
    lines, at = [], 0
    for offset, (kind, size, text) in sorted(members.items()):
        if offset < at:
            return None
        if offset > at:
            lines.append(f'{indent}char pad{at:X}[0x{offset - at:X}];')
        lines.append(f'{indent}{text}')
        at = offset + size
    if at > total:
        return None
    if total > at:
        lines.append(f'{indent}char pad{at:X}[0x{total - at:X}];')
    return lines


def variants(source, name, header='', asm=''):
    span = find(source, name)
    if not span or re.search(r'\b' + TAG + r'\b', source + header):
        return []
    head, body, tail = source[:span[0]], _blank(source[span[0]:span[1]]), source[span[1]:]
    original = source[span[0]:span[1]]
    original, carried = _offset_temps(original, body)
    body = _blank(original)
    temps = {}
    for m in re.finditer(r'(?m)^[ \t]*([A-Za-z_]\w*)\s*=\s*([^=;][^;]*);', body):
        temps.setdefault(m[1], []).append((m.start(), m[2].strip()))
    widths = _target_widths(asm)
    accesses = _accesses(body, temps, widths)
    if not accesses:
        return []
    stride = max(scale for a in accesses for _, scale in a[5])
    others = [a for a in accesses if all(scale != stride for _, scale in a[5])]
    accesses = [a for a in accesses if a not in others]
    if len(accesses) < 3 or any(a[4] is None for a in accesses):
        return []
    # The record starts where every member is aligned in it: the lowest address read can be a byte field in the
    # middle of the first word (a state byte at +1), and a base there puts the halfwords and words at odd offsets,
    # which the compiler pads to other addresses.
    align = max(_SIZE[a[4]] for a in accesses)
    base = min(a[3] for a in accesses) // align * align
    if stride % align or any((a[3] - base) % _SIZE[a[4]] for a in accesses):
        return []
    if any(base <= a[3] < base + stride for a in others):
        return []
    rows = f'D_{base:08X}'
    direct, nested, inner_scale = {}, {}, None
    for _, _, _, address, kind, indices in accesses:
        outer = [i for i in indices if i[1] == stride]
        rest = [i for i in indices if i[1] != stride]
        offset = address - base
        if len(outer) != 1 or len(rest) > 1 or offset + _SIZE[kind] > stride:
            return []
        if rest:
            if inner_scale not in (None, rest[0][1]):
                return []
            inner_scale = rest[0][1]
            if nested.setdefault(offset, kind) != kind:
                return []
        elif direct.setdefault(offset, kind) != kind:
            return []
    members = {o: (k, _SIZE[k], f'{k} m{o:X};') for o, k in direct.items()}
    start, plain = None, False
    if nested:
        start = min(nested)
        if max(o + _SIZE[k] for o, k in nested.items()) - start > inner_scale:
            return []
        end = min([o for o in direct if o > start] + [stride])
        count = (end - start) // inner_scale
        fields = {o - start: (k, _SIZE[k], f'{k} m{o - start:X};') for o, k in nested.items()}
        lines = _member_lines(fields, inner_scale, '        ')
        if lines is None or not count or start in members:
            return []
        # one field that fills the element is a plain array: GCC then keeps its address in a register of its own
        plain = len(fields) == 1 and 0 in fields and fields[0][1] == inner_scale
        members[start] = (None, count * inner_scale,
                          f'{fields[0][0]} m{start:X}[{count}];' if plain else
                          'struct {\n' + '\n'.join(lines) + f'\n    }} m{start:X}[{count}];')
    lines = _member_lines(members, stride, '    ')
    if lines is None:
        return []
    record = 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {TAG};\nextern {TAG} {rows}[];\n\n'

    edits = []
    for a, b, _, address, kind, indices in accesses:
        index = next(i for i, scale in indices if scale == stride)
        offset = address - base
        rest = [i for i, scale in indices if scale != stride]
        member = f'm{offset:X}'
        if rest:
            member = f'm{start:X}[{rest[0]}]' + ('' if plain else f'.m{offset - start:X}')
        edits.append((a, b, f'{rows}[{index}].{member}'))
    symbols = {a[2] for a in accesses} | {rows}
    # the record's own address passed on: `i * STRIDE + &D` is `&D[i]`
    taken = [(a, b) for a, b, _ in edits]
    names = '|'.join(re.escape(t) for t in temps) or r'(?!)'
    term = r'(?:\b(?:' + names + r')\b|\([^()]*\)\s*\*\s*\w+|\b\w+\s*\*\s*\w+)'
    symbol = r'(?:\([ \t]*(?:char|s8|u8)[ \t]*\*[ \t]*\)[ \t]*)?&?[ \t]*' + re.escape(rows) + r'\b'
    for m in re.finditer(r'(?<=[(,])\s*(?:(?:' + term + r')\s*\+\s*' + symbol + r'|' + symbol + r'\s*\+\s*' + term
                         + r')\s*(?=[,)])', body):
        if any(a <= m.start() < b for a, b in taken):
            continue
        terms = _terms(m[0], temps, m.start())
        if terms and terms[0] == [rows] and not terms[1] and len(terms[2]) == 1 and terms[2][0][1] == stride:
            edits.append((m.start(), m.end(), f'&{rows}[{terms[2][0][0]}]'))
    edits.sort()
    if any(first[1] > second[0] for first, second in zip(edits, edits[1:])):
        return []
    text = original
    for a, b, replacement in reversed(edits):
        text = text[:a] + replacement + text[b:]
    # the temporaries that only carried the products
    for temp in temps:
        uses = len(re.findall(r'\b' + temp + r'\b', _blank(text)))
        assigned = len(re.findall(r'(?m)^[ \t]*' + temp + r'\s*=[^=;][^;]*;[ \t]*\n', text))
        declared = re.search(r'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+\*?[ \t]*' + temp + r'\s*;[ \t]*\n', text)
        if assigned and declared and uses == assigned + 1:
            text = re.sub(r'(?m)^[ \t]*' + temp + r'\s*=[^=;][^;]*;[ \t]*\n', '', text)
            text = re.sub(r'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+\*?[ \t]*' + temp + r'\s*;[ \t]*\n', '', text)
    for each in symbols:
        declaration = r'(?m)^[ \t]*extern[ \t]+[\w \t]+?[ \t*]' + each + r'\s*(?:\[[^\]\n]*\])?\s*;[^\n]*\n'
        if re.search(r'\b' + each + r'\b', header):
            return []
        head = re.sub(declaration, '', head)
        if re.search(r'\b' + each + r'\b', head):
            return []
        left = re.sub(r'&?' + re.escape(rows) + r'\[', '', _blank(text))
        if re.search(r'\b' + each + r'\b', left):
            return []
    out = head + record + text + tail
    if carried:
        out = _other_tables(out, carried, stride)
    return [(FAMILY, out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'archs': ('mips',)}
