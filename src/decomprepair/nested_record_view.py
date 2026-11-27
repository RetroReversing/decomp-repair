"""A byte-arithmetic address `base + I * S1 + c1 + J * S2 + c2` written as nested arrays of records through a view
type, `&((View *) base)->r[I].r[J]`, with an index byte read `M2C_FIELD(base + K * S0, u8 *, c0)` the same way.

gcc 2.7.2 expands an `ARRAY_REF` chain as `((I * S1 + c1) + base) + (J * S2 + c2)`, each level's product and offset
summed before the base joins, and a record member read `base->slots[K].f` as `base + K * S0` with the offset in the
load. The same sum written as byte arithmetic (any grouping, casts or locals) is reassociated by fold and combine, so
the base, the field and the partial sums take other registers. On an N64 function (KMC GCC 2.7.2, `-O1 -g`,
99 instructions; a game-state record holding 0x510-byte rows of 0xC-byte entries, indexed by a byte read from a table
of 16-byte slots) every byte-arithmetic grouping scored 275 or 585 and the saved best 130; with the rows and the slot
read typed it was exact (130 -> 0). Typing only the rows and leaving the slot read in bytes stayed at 275.

nested_record_view
    `X = SUM;` (also `X = (T *)(SUM)`, and SUM spread over once-used locals initialised in their declarations), where
    SUM's terms are one name B, 1-3 products `E * S` with distinct constant strides and constants, becomes
    `X = &((V *) B)->r[E1].r[E2]...;` with the view typedefs written before the function: the record of each level is
    S bytes with the next level's array at its offset (offsets paired with the products they follow; when the counts
    differ, all on the outer level and, as a second child, all on the inner one). A byte read
    `M2C_FIELD(B + K * S0, T *, c0)` in an index becomes `((W *) B)->r[K].f`. The judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'nested_record_view'
FAMILIES = (FAMILY,)
LIMIT = 4
SCALAR = r'(?:(?:un)?signed\s+)?(?:char|short|int|long)|[su](?:8|16|32)|void|M2C_UNK\w*'
CAST = re.compile(r'\(\s*(?:' + SCALAR + r')\s*\**\s*\)\s*')
ASSIGN = re.compile(r'(?<=[;{}])\s*(?P<x>' + IDENT + r')\s*=(?!=)\s*(?P<e>[^;{}]+);')
INIT = re.compile(r'(?<=[;{}])\s*(?:' + SCALAR + r')\s*\**\s*(?P<n>' + IDENT + r')\s*=(?!=)\s*(?P<e>[^;{}]+);')
FIELD = re.compile(r'M2C_FIELD\(\s*(?P<a>.+?)\s*,\s*(?P<t>(?:(?:un)?signed\s+)?(?:char|short)|[su](?:8|16))\s*\*\s*,\s*'
                   r'(?P<c>' + NUMBER + r')\s*\)$')
WIDTH = {'u8': 1, 's8': 1, 'char': 1, 'unsigned char': 1, 'signed char': 1,
         'u16': 2, 's16': 2, 'short': 2, 'unsigned short': 2, 'signed short': 2}


def _number(text):
    return int(text.rstrip('uUlL'), 0)


def _strip(text):
    """`text` without whitespace, outer brackets and scalar casts around the whole of it."""
    while True:
        text = text.strip()
        cast = CAST.match(text)
        if cast:
            rest = text[cast.end():]
            if re.fullmatch(IDENT, rest) or rest.startswith('(') and close(rest, 0, '(', ')') == len(rest):
                text = rest
                continue
        if text.startswith('(') and close(text, 0, '(', ')') == len(text):
            text = text[1:-1]
            continue
        return text


def _split(text, operator):
    """Top-level operands of `operator` (`+` or `*`), or None when a `-`, a shift or a comparison is at top level."""
    pieces, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0:
            if char == operator:
                pieces.append(text[start:index])
                start = index + 1
            elif char in '-<>?:=&|^!/%':
                if char == '-' and text[index + 1:index + 2] == '>':
                    continue
                return None
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces]


def _terms(text):
    """Flattened `+` terms: ('base', name), ('const', value), ('product', expr, stride), or None."""
    parts = _split(_strip(text), '+')
    if parts is None:
        return None
    if len(parts) == 1:
        return [_term(parts[0])]
    out = []
    for part in parts:
        inner = _terms(part)
        if inner is None:
            return None
        out += inner
    return out


def _term(text):
    text = _strip(text)
    if re.fullmatch(NUMBER, text):
        return ('const', _number(text))
    if re.fullmatch(IDENT, text):
        return ('base', text)
    factors = _split(text, '*')
    if factors and len(factors) == 2:
        for a, b in (factors, factors[::-1]):
            if re.fullmatch(NUMBER, _strip(b)) and not re.fullmatch(NUMBER, _strip(a)):
                return ('product', _strip(a), _number(_strip(b)))
    if factors and len(factors) > 2:
        return None
    sub = _split(text, '+')
    if sub and len(sub) > 1:
        return None
    return ('other', text)


def _inline(part, source, expression, start):
    """`expression` with each once-used local initialised in its declaration (before `start`) written in; the
    declarations to delete."""
    removed = []
    for _ in range(3):
        changed = False
        for hit in INIT.finditer(part.clean, part.opening + 1, start):
            name = hit['n']
            uses = [u for u in re.finditer(rf'(?<![\w.>]){name}\b', part.clean[part.opening + 1:part.end])]
            if len(uses) != 2 or not re.search(rf'(?<![\w.>]){name}\b', expression):
                continue
            value = source[hit.start('e'):hit.end('e')]
            expression = re.sub(rf'(?<![\w.>]){name}\b', lambda _m, v=value: f'({v})', expression, count=1)
            removed.append((hit.start(), hit.end()))
            changed = True
        if not changed:
            break
    return expression, removed


def _layout(levels, base, view_name):
    """Typedefs and the access for levels [(index, stride, offset)] (outermost first)."""
    defs = []
    element = f'struct {{ u8 b[{levels[-1][1]:#x}]; }}'
    for depth in range(len(levels) - 1, 0, -1):
        stride, (_index, inner_stride, inner_offset) = levels[depth - 1][1], levels[depth]
        if inner_offset + inner_stride > stride:
            return None
        count = (stride - inner_offset) // inner_stride
        tail = stride - inner_offset - count * inner_stride
        members = (f'u8 pad[{inner_offset:#x}]; ' if inner_offset else '') + f'{element} r[{count}];' + (
            f' u8 tail[{tail:#x}];' if tail else '')
        element = f'struct {{ {members} }}'
    top = levels[0][2]
    defs.append(f'typedef struct {{ {f"u8 pad[{top:#x}]; " if top else ""}{element} r[1]; }} {view_name};')
    access = f'((({view_name} *) {base})->r' + ''.join(f'[{index}]' + ('.r' if i < len(levels) - 1 else '')
                                                       for i, (index, _s, _o) in enumerate(levels)) + ')'
    return defs, access


def _slot_reads(index, base, name, used):
    """Index text with `M2C_FIELD(base + K * S0, T *, c0)` reads written through a view; (text, typedefs)."""
    defs = []
    out, position = [], 0
    for hit in re.finditer(r'M2C_FIELD\(', index):
        end = close(index, hit.end() - 1, '(', ')')
        if not end or hit.start() < position:
            continue
        field = FIELD.fullmatch(index[hit.start():end])
        if not field:
            continue
        terms = _terms(field['a'])
        if not terms or [t[0] for t in terms].count('base') != 1 or [t for t in terms if t[0] == 'base'][0][1] != base:
            continue
        products = [t for t in terms if t[0] == 'product']
        consts = sum(t[1] for t in terms if t[0] == 'const')
        if len(products) != 1 or any(t[0] == 'other' for t in terms):
            continue
        _k, key, stride = products[0]
        offset = consts + _number(field['c'])
        kind = ' '.join(field['t'].split())
        width = WIDTH[kind]
        at = offset % stride
        if at + width > stride:
            continue
        used[0] += 1
        view_name = f'{name}_view{used[0]}'
        members = (f'u8 pad[{at:#x}]; ' if at else '') + f'{kind} f;' + (
            f' u8 tail[{stride - at - width:#x}];' if stride - at - width else '')
        row_at = offset - at
        defs.append(f'typedef struct {{ {f"u8 pad[{row_at:#x}]; " if row_at else ""}struct {{ {members} }} r[1]; }} '
                    f'{view_name};')
        out.append(index[position:hit.start()] + f'(({view_name} *) {base})->r[{key}].f')
        position = end
    out.append(index[position:])
    return ''.join(out), defs


def _base_global(child, base, access):
    """The child with a base local `T base = G;` read as G in the access, its declaration gone, when the access was
    its only other use: the local is a pseudo of its own, and the base's operand of the last add swapped (5 -> 0)."""
    declaration = re.search(rf'(?m)^[ \t]*(?:{SCALAR})\s*\**\s*{base}\s*=\s*({IDENT})\s*;[ \t]*\n', child)
    if not declaration or child.count(access) != 1:
        return None
    rest = child[:declaration.start()] + child[declaration.end():]
    if len(re.findall(rf'(?<![\w.>]){base}\b', rest.replace(access, ''))) != 0:
        return None
    return rest.replace(access, re.sub(rf'(?<![\w.>]){base}\b', declaration[1], access))


def _declared_pointer(part, x):
    return bool(re.search(rf'(?<![\w.>])[\w ]*\*\s*{x}\s*;', part.clean[part.opening:part.end]))


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    out = []
    head = source.rfind('\n', 0, source.rfind(name, 0, part.opening)) + 1
    for hit in ASSIGN.finditer(part.clean, part.opening + 1, part.end):
        expression, removed = _inline(part, source, source[hit.start('e'):hit.end('e')], hit.start())
        terms = _terms(expression)
        if not terms or [t[0] for t in terms].count('base') != 1 or any(t[0] == 'other' for t in terms):
            continue
        base = next(t[1] for t in terms if t[0] == 'base')
        products = [t for t in terms if t[0] == 'product']
        if not 1 <= len(products) <= 3 or len({t[2] for t in products}) != len(products) or len(products) == 1 and not any(
                t[0] == 'const' for t in terms):
            continue
        # constants paired with the product they follow
        paired, pending, consts = {}, None, []
        for term in terms:
            if term[0] == 'product':
                pending = term
                paired.setdefault(id(term), 0)
            elif term[0] == 'const':
                consts.append(term[1])
                if pending is not None:
                    paired[id(pending)] += term[1]
                    pending = None
        ordered = sorted(products, key=lambda t: -t[2])
        plans = []
        if len(consts) == len(products) and all(paired[id(t)] or not consts for t in products) and \
                sum(paired.values()) == sum(consts):
            plans.append([paired[id(t)] for t in ordered])
        total = sum(consts)
        plans.append([total] + [0] * (len(ordered) - 1))
        if len(ordered) > 1:
            plans.append([0] * (len(ordered) - 1) + [total])
        used = [0]
        for plan in plans:
            if len(out) >= LIMIT:
                break
            defs, levels = [], []
            for (_kind, index, stride), offset in zip(ordered, plan):
                text, slot_defs = _slot_reads(index, base, name, used)
                defs += slot_defs
                levels.append((text, stride, offset))
            used[0] += 1
            layout = _layout(levels, base, f'{name}_view{used[0]}')
            if not layout:
                continue
            defs += layout[0]
            access = '&' + layout[1]
            x = hit['x']
            value = access if _declared_pointer(part, x) else f'(s32) {access}'
            edits = [(head, head, '\n'.join(defs) + '\n'), (hit.start('e'), hit.end('e'), value)]
            edits += [(start, end, '') for start, end in removed]
            child = edit(source, edits)
            out.append(_base_global(child, base, access) or child)
            out.append(child)
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
