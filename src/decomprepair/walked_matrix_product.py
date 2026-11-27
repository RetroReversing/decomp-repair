"""m2c's walked 4x4 float matrix product, written back as the two indexed loops it came from.

A `guMtxCatF` shape (two 0x40-byte buffers multiplied into a third, often inlined between `guMtxL2F` and `guMtxF2L`)
is drafted as `goto` loops over a row cursor stepped by 0x10, a column cursor stepped by 4, a byte offset and a
pointer into the result:

    row = a; i = 0;
  outer:
    { j = 0; col = b; off = i * 0x10;
    inner:
      { dst = d + off; off += 4; j += 1;
        *dst = *(f32 *) ((char *) row) * *(f32 *) ((char *) col) + ... + *(f32 *) ((char *) row + 0xC) * ...;
        col += 4; }
      if (j < 4) goto inner;
      row += 0x10; i += 1; }
    if (i < 4) goto outer;

The game declared `f32 a[4][4], b[4][4], d[4][4];` and wrote
`d[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j];` in two `for` loops. An SN
GCC 2.8.1 (`-O2 -mfp32`) function matched with it from a best of 984 no single rewrite moved below 924: the buffers'
type matters (`char[0x40]` read through casts scored 3959 with the same loops), and so does the order of each
product's operands (20 with the last one swapped).

Offered only when every part of the walk is proven: three 0x40-byte local buffers, the four products paired row `4k`
with column `0x10k` in left-to-right order, both counters running 0 to 3, each cursor started at its buffer and stepped
once at the right depth, and nothing else done in the loops. Children: row operand first in each product (the SDK's
order), the operands as the draft wrote them, and column first. The sum is never reassociated. The judge decides."""
import re

from .arm_block_support import IDENT, brace_pairs, statements
from .integer_repair_support import edit, view

FAMILY = 'walked_matrix_product'
FAMILIES = (FAMILY,)

_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_BUFFER = re.compile(rf'(?:(?:char|s8|u8)\s+(?P<a>{IDENT})\s*\[\s*(?:0x40|64)\s*\]'
                     rf'|(?:f32|float|s32|u32)\s+(?P<b>{IDENT})\s*\[\s*(?:0x10|16)\s*\]'
                     rf'|(?:f32|float)\s+(?P<c>{IDENT})\s*\[\s*4\s*\]\s*\[\s*4\s*\])\s*;')
_SCALAR = re.compile(rf'(?:char|s8|u8|f32|float|s32|u32|int|void)\s*\**\s*(?P<name>{IDENT})\s*;')
_FLOAT = r'(?:f32|float)\*'
_BYTE = r'(?:char|s8|u8)\*'
_LOADS = tuple(re.compile(p) for p in (
    rf'\*\(\({_FLOAT}\)\(\(\({_BYTE}\)(?P<v>{IDENT})\)(?:\+(?P<k>{_NUM}))?\)\)',
    rf'\*\({_FLOAT}\)\(\(\({_BYTE}\)(?P<v>{IDENT})\)(?:\+(?P<k>{_NUM}))?\)',
    rf'\*\({_FLOAT}\)\(\({_BYTE}\)(?P<v>{IDENT})(?:\+(?P<k>{_NUM}))?\)',
    rf'\*\({_FLOAT}\)\((?P<v>{IDENT})\+(?P<k>{_NUM})\)',
    rf'M2C_FIELD\((?P<v>{IDENT}),{_FLOAT},(?P<k>{_NUM})\)',
    rf'\((?P<v>{IDENT})\)->unk(?P<h>[0-9A-F]+)',
    rf'(?<![\w.])(?P<v>{IDENT})->unk(?P<h>[0-9A-F]+)',
    rf'\*\({_FLOAT}\)(?P<v>{IDENT})(?![\w(\[])',
))


def _number(text):
    return int(text, 16) if text.lower().startswith('0x') else int(text)


def _sum_terms(text):
    """The left-to-right products of a sum of two-load products, [((v, k), (v, k)), ...]; None otherwise."""
    loads = []

    def token(found):
        offset = found.groupdict().get('h')
        offset = int(offset, 16) if offset is not None else _number(found.groupdict().get('k') or '0')
        loads.append((found['v'], offset))
        return f'@{len(loads) - 1};'

    compact = re.sub(r'\s+', '', text)
    for pattern in _LOADS:
        compact = pattern.sub(token, compact)
    tokens = re.findall(r'@\d+;|[()+*]', compact)
    if ''.join(tokens) != compact:
        return None
    at = 0

    def factor():
        nonlocal at
        if at >= len(tokens):
            raise ValueError
        word = tokens[at]
        at += 1
        if word.startswith('@'):
            return ('load', loads[int(word[1:-1])])
        if word != '(':
            raise ValueError
        inner = total()
        if at >= len(tokens) or tokens[at] != ')':
            raise ValueError
        at += 1
        return inner

    def product():
        nonlocal at
        left = factor()
        while at < len(tokens) and tokens[at] == '*':
            at += 1
            right = factor()
            if left[0] != 'load' or right[0] != 'load':
                raise ValueError
            left = ('mul', (left[1], right[1]))
        return left

    def total():
        nonlocal at
        left = product()
        while at < len(tokens) and tokens[at] == '+':
            at += 1
            right = product()
            if right[0] != 'mul' or left[0] not in ('mul', 'sum'):
                raise ValueError  # (a sum on the right is another association: not the loop's expression)
            left = ('sum', (left[1] if left[0] == 'sum' else [left[1]]) + [right[1]])
        return left

    try:
        tree = total()
    except ValueError:
        return None
    return tree[1] if at == len(tokens) and tree[0] == 'sum' and len(tree[1]) == 4 else None


def _operands(terms):
    """(row cursor, column cursor, [row written first, per term]) of the four products; None when they do not pair."""
    for row, column in ((terms[0][0][0], terms[0][1][0]), (terms[0][1][0], terms[0][0][0])):
        if row == column:
            return None
        order = []
        for k, (left, right) in enumerate(terms):
            if left == (row, 4 * k) and right == (column, 16 * k):
                order.append(True)
            elif left == (column, 16 * k) and right == (row, 4 * k):
                order.append(False)
            else:
                break
        else:
            return row, column, order
    return None


def _steps(body, name):
    return [m.start() for m in re.finditer(
        rf'(?<![\w.>]){name}\s*(?:\+=\s*(?P<k>{_NUM})|\+\+|=\s*{name}\s*\+\s*(?P<l>{_NUM}))\s*;', body)]


def _step_by(body, name, size):
    """Where `name` is stepped, when it is stepped exactly once and by `size`."""
    found = list(re.finditer(
        rf'(?<![\w.>]){name}\s*(?:\+=\s*(?P<k>{_NUM})|(?P<inc>\+\+)|=\s*{name}\s*\+\s*(?P<l>{_NUM}))\s*;', body))
    if len(found) != 1:
        return None
    amount = 1 if found[0]['inc'] else _number(found[0]['k'] or found[0]['l'])
    return found[0] if amount == size else None


def _assignments(body, name):
    return list(re.finditer(rf'(?<![\w.>*]){name}\s*=(?!=)\s*(?!{name}\s*\+)(?P<value>[^;]*);', body))


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|switch|return)\b', part.clean[part.opening:part.end]):
        return []
    clean, lo = part.clean, part.opening + 1
    hi = clean.rfind('}', lo, part.end)
    if hi < 0:
        return []
    top = statements(clean, lo, hi)
    buffers, scalars = {}, {}
    for start, end in top:
        text = clean[start:end]
        if found := _BUFFER.fullmatch(text):
            buffers[found['a'] or found['b'] or found['c']] = (start, end)
        elif found := _SCALAR.fullmatch(text):
            scalars[found['name']] = (start, end)
    if len(buffers) < 3:
        return []

    stores = []
    for found in re.finditer(r'(?<=[;{}:])\s*(?P<lhs>\*[^;{}=]*?)\s*=(?!=)\s*(?P<rhs>[^;]*);', clean[lo - 1:hi]):
        terms = _sum_terms(found['rhs'])
        if terms and (operands := _operands(terms)):
            stores.append((found, operands))
    if len(stores) != 1:
        return []
    store, (row, column, order) = stores[0]
    at = lo - 1 + store.start('lhs')

    # the loops: the top-level statement holding the store, to the last `goto` back into it
    first = next((i for i, (start, end) in enumerate(top) if start <= at < end), None)
    if first is None:
        return []
    start = top[first][0]
    labels = re.findall(rf'(?<![\w?:])({IDENT})\s*:(?!:)', clean[start:top[first][1]])
    last = first
    for i in range(first + 1, len(top)):
        if any(re.search(rf'\bgoto\s+{label}\s*;', clean[top[i][0]:top[i][1]]) for label in labels):
            last = i
    end = top[last][1]
    region = clean[start:end]
    if any(re.search(rf'\bgoto\s+{label}\s*;', clean[lo:start] + clean[end:hi]) for label in labels):
        return []

    # the destination pointer and its byte offset
    target = re.fullmatch(rf'\*\s*(?P<dst>{IDENT})', store['lhs'])
    if not target:
        return []
    dst = target['dst']
    points = _assignments(region, dst)
    if len(points) != 1:
        return []
    value = re.sub(r'\s+', '', points[0]['value'])
    place = re.fullmatch(rf'(?:\((?:{_FLOAT}|{_BYTE})\))?(?:\((?:{_BYTE})\))?\(?(?P<buf>{IDENT})\)?\+(?P<off>{IDENT})',
                         value)
    if not place or place['buf'] not in buffers:
        return []
    out, offset = place['buf'], place['off']
    inits = _assignments(region, offset)
    if len(inits) != 1:
        return []
    scaled = re.fullmatch(rf'({IDENT})\s*(?:\*\s*(?:0x10|16)|<<\s*4)', inits[0]['value'].strip())
    if not scaled:
        return []
    outer = scaled[1]
    conditions = re.findall(rf'\b(?:if|while)\s*\(\s*({IDENT})\s*(?:<|!=)\s*(?:4|0x4)\s*\)', region)
    inner = [c for c in conditions if c != outer]
    if len(conditions) != 2 or len(inner) != 1 or outer not in conditions:
        return []
    inner = inner[0]
    walked = (row, column, offset, outer, inner, dst)
    if len(set(walked)) != 6 or not all(v in scalars for v in walked):
        return []
    for cursor in (row, column):  # byte cursors only: the steps below are in bytes
        if not re.match(r'(?:char|s8|u8|void)\s*\*', clean[slice(*scalars[cursor])]):
            return []

    # which statements run once per column
    braces = brace_pairs(clean, start, end)
    if braces is None:
        return []
    spot = at
    blocks = sorted((close - opening, opening, close) for opening, close in braces.items() if opening < spot < close)
    if not blocks:
        return []
    _, inner_open, inner_close = blocks[0]

    def within(match):
        return inner_open < start + match.start() < inner_close

    sources = {}
    for cursor in (row, column):
        starts = _assignments(clean[lo:end], cursor)
        if len(starts) != 1:
            return []
        buf = re.fullmatch(rf'(?:\(\s*(?:{IDENT})\s*\*\s*\)\s*)?&?({IDENT})', starts[0]['value'].strip())
        if not buf or buf[1] not in buffers:
            return []
        sources[cursor] = (buf[1], lo + starts[0].start())
    a, b = sources[row][0], sources[column][0]
    if len({a, b, out}) != 3 or not start <= sources[column][1] < inner_open:
        return []
    counts = {}
    for counter in (outer, inner):
        starts = _assignments(clean[lo:end], counter)
        if len(starts) != 1 or starts[0]['value'].strip() != '0':
            return []
        counts[counter] = lo + starts[0].start()
    row_step, column_step = _step_by(region, row, 0x10), _step_by(region, column, 4)
    offset_step, outer_step = _step_by(region, offset, 4), _step_by(region, outer, 1)
    inner_step = _step_by(region, inner, 1)
    if not all((row_step, column_step, offset_step, outer_step, inner_step)):
        return []
    if (within(row_step) or within(outer_step) or within(inits[0])
            or not all(within(step) for step in (column_step, offset_step, inner_step, points[0]))
            or not points[0].start() < offset_step.start()
            or start + column_step.start() < at
            or not start <= counts[inner] < inner_open
            or counts[outer] > inner_open or sources[row][1] > inner_open):
        return []

    # nothing else happens in the loops
    rest = region
    rest = re.sub(rf'\b(?:if|while)\s*\(\s*(?:{outer}|{inner})\s*(?:<|!=)\s*(?:4|0x4)\s*\)', ' ', rest)
    rest = re.sub(r'\bwhile\s*\(\s*0\s*\)|\bdo\b', ' ', rest)
    rest = rest.replace(store.group()[store.start('lhs') - store.start():], ' ')
    rest = re.sub(rf'\bgoto\s+(?:{"|".join(labels) or "_"})\s*;', ' ', rest)
    for label in labels:
        rest = re.sub(rf'(?<![\w]){label}\s*:', ' ', rest)
    loop_locals = '|'.join(walked)
    rest = re.sub(rf'(?<![\w.>*])(?:{loop_locals})\s*(?:\+\+|\+?=(?!=)[^;{{}}]*)\s*;', ' ', rest)
    if re.sub(r'[\s{};]', '', rest):
        return []

    # before the loops the cursors only start, or are passed on as their buffer; after them nothing is left of them
    edits = []
    for i, (s, e) in enumerate(top):
        if first <= i <= last or (s, e) in scalars.values():
            continue
        text = clean[s:e]
        used = [v for v in walked if re.search(rf'(?<![\w.>]){v}\b', text)]
        if not used:
            continue
        if i > last:
            return []
        lone = re.fullmatch(rf'({IDENT})\s*=(?!=)[^;]*;', text)
        if lone and lone[1] in (row, outer):
            edits.append((s, e, ''))
            continue
        if set(used) - {row} or not re.match(rf'{IDENT}\s*\(', text):
            return []
        for use in re.finditer(rf'(?<![\w.>]){row}\b', text):
            before, after = text[:use.start()].rstrip(), text[use.end():].lstrip()
            if before[-1:] not in '(,' or after[:1] not in ',)':
                return []
            edits.append((s + use.start(), s + use.end(), a))
    for buf in (a, b, out):  # other uses pass the whole buffer, so a float matrix passes the same address
        for use in re.finditer(rf'(?<![\w.>]){buf}\b', clean[lo:start] + ' ' * (end - start) + clean[end:hi]):
            s = lo + use.start()
            if buffers[buf][0] <= s < buffers[buf][1]:
                continue
            statement = next(((x, y) for x, y in top if x <= s < y), None)
            if statement and statement[0] in [x for x, _, _ in edits]:
                continue
            before, after = clean[lo:s].rstrip(), clean[s + len(buf):hi].lstrip()
            if before[-1:] not in '(,' or after[:1] not in ',)':
                return []

    taken = set(re.findall(IDENT, part.clean + ' ' + header)) - set(walked)
    pair = next((p for p in (('i', 'j'), ('row', 'col'), ('r', 'c')) if not set(p) & taken), None)
    if not pair:
        return []
    i_name, j_name = pair
    for local in walked:
        edits.append((*scalars[local], ''))
    for buf in (a, b, out):
        edits.append((*buffers[buf], f'f32 {buf}[4][4];'))
    indent = re.search(r'[ \t]*$', source[lo:top[0][0]])[0] or '    '
    counters_after = max(e for _, e in list(buffers.values()) + list(scalars.values()))
    edits.append((counters_after, counters_after, f'\n{indent}s32 {i_name};\n{indent}s32 {j_name};'))

    def child(firsts):
        products = []
        for k, row_first in enumerate(firsts):
            left, right = f'{a}[{i_name}][{k}]', f'{b}[{k}][{j_name}]'
            products.append(f'{left} * {right}' if row_first else f'{right} * {left}')
        loops = (f'for ({i_name} = 0; {i_name} < 4; {i_name}++) {{\n'
                 f'{indent}{indent}for ({j_name} = 0; {j_name} < 4; {j_name}++) {{\n'
                 f'{indent}{indent}{indent}{out}[{i_name}][{j_name}] = {" + ".join(products)};\n'
                 f'{indent}{indent}}}\n{indent}}}')
        return edit(source, edits + [(start, end, loops)])

    result = []
    for firsts in ([True] * 4, order, [False] * 4):
        text = re.sub(r'\n(?:[ \t]*\n)+', '\n', child(firsts))
        if (FAMILY, text) not in result:
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}
