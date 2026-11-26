"""A record table reached through an array member, for gcc 2.7.2's operand order of `BASE + (i * 16)`.

`*(T *)(BASE + (i * 16) + K)` and m2c's `M2C_FIELD((BASE + (i * 16)), T *, K)` are pointer arithmetic: gcc 2.7.2
expands the scaled term in address mode, as `(mult i 16)`, which rtl canonicalisation puts before the base, so the
`addu` reads `addu $v1, $shift, $base`. The game's own source indexed an array of records inside a structure
(`g->players[i].field`). That is an ARRAY_REF, whose address is built as `array_address + index * size` with the
index term already reduced to a register, and its `addu` is `addu $v1, $base, $shift`. Measured with KMC gcc 2.7.2
`-G0 -mips3 -mgp32 -mfp32` (judge, three open functions of an N64 racing game at 5, 5 and 10 -> 0): the byte-row
subscript `((u8 (*)[16]) BASE)[i][K]` (`row_subscript`), a pointer to an array of records, `(T (*)[N])`, and a cast of
the base to a record pointer indexed with `[i]` all stay pointer arithmetic and keep the order; only an array *member*
of a structure reached through the cast base makes the other order:

    struct __rows_BASE_10 { char pad[0x2980]; struct { char p0[11]; u8 m_b; s8 m_c; char p1[3]; } e[1]; };
    ((struct __rows_BASE_10 *)BASE)->e[i].m_c = x;

Each group of accesses that share a base, an index variable and a power-of-two-or-not stride becomes one structure
declared before the function (the rows start at the largest multiple of the stride at or below the lowest offset;
members are placed at their offsets, a union where two types share one) and every access of the group is rewritten.
Accesses that do not fit one row (past the stride, misaligned for their width) stay as they were. Two children: every
group at once, and each group alone when there are several. The judge decides each.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'member_array_rows'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4}
CAST = re.compile(r'^\(\s*(?:(?:unsigned|signed|const)\s+)*(?:s8|u8|s16|u16|s32|u32|char|short|int|void)\s*\*?\s*\)\s*')
MAX_CHILDREN = 8


def _strip(text):
    """`text` without its outer parentheses and leading integer or byte-pointer casts."""
    text = text.strip()
    while True:
        if text.startswith('('):
            end = close(text, 0, '(', ')')
            if end == len(text):
                text = text[1:-1].strip()
                continue
        cast = CAST.match(text)
        if cast and len(text) > cast.end():
            text = text[cast.end():].strip()
            continue
        return text


def _split(text):
    """Top-level `+` terms of `text`, or None when it has a top-level `-`, `*` mixed with others or a bracket."""
    parts, depth, start = [], 0, 0
    for at, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and char == '+':
            parts.append(text[start:at])
            start = at + 1
        elif depth == 0 and char in '-/%&|^<>?:=,!':
            if char == '<' and text[at:at + 2] == '<<':
                continue
            if char == '<' and text[at - 1:at] == '<':
                continue
            return None
    parts.append(text[start:])
    return parts


def _leaves(text):
    """Every additive leaf of an address expression, casts and parentheses peeled; None when it is not a sum."""
    text = _strip(text)
    parts = _split(text)
    if parts is None:
        return None
    if len(parts) == 1:
        return [text]
    out = []
    for part in parts:
        inner = _leaves(part)
        if inner is None:
            return None
        out.extend(inner)
    return out


def analyze(expr):
    """(base, index, stride, constant) of `BASE + index * stride + K` in any order, else None."""
    leaves = _leaves(expr)
    if not leaves:
        return None
    base = index = stride = None
    constant = 0
    for leaf in leaves:
        leaf = _strip(leaf)
        number = re.fullmatch(NUMBER, leaf)
        scaled = (re.fullmatch(rf'({IDENT})\s*\*\s*({NUMBER})', leaf) or re.fullmatch(rf'({NUMBER})\s*\*\s*({IDENT})', leaf)
                  or re.fullmatch(rf'({IDENT})\s*<<\s*({NUMBER})', leaf))
        if number:
            constant += int(leaf, 0)
        elif scaled:
            first, second = scaled.groups()
            if '<<' in leaf:
                name, size = first, 1 << int(second, 0)
            elif re.fullmatch(NUMBER, first):
                name, size = second, int(first, 0)
            else:
                name, size = first, int(second, 0)
            if index is not None:
                return None
            index, stride = name, size
        elif re.fullmatch(IDENT, leaf):
            if base is not None:
                return None
            base = leaf
        else:
            return None
    if base is None or index is None or index == base or stride < 2:
        return None
    return base, index, stride, constant


def _accesses(source, clean, start, end):
    """[(span_start, span_end, kind, base, index, stride, offset)] for each rewritable access in clean[start:end]."""
    found = []
    taken = 0
    pattern = re.compile(r'M2C_FIELD\s*\(|\*\s*\(\s*(?:(?:unsigned|signed)\s+)?\w+\s*\*\s*\)\s*\(')
    for match in pattern.finditer(clean, start, end):
        if match.start() < taken:
            continue
        opening = match.end() - 1
        stop = close(clean, opening, '(', ')')
        if not stop:
            continue
        inner = source[opening + 1:stop - 1]
        if match.group().startswith('M2C_FIELD'):
            depth, cuts = 0, []
            for at, char in enumerate(inner):
                depth += char in '([{'
                depth -= char in ')]}'
                if char == ',' and depth == 0:
                    cuts.append(at)
            if len(cuts) != 2:
                continue
            expr, kind, extra = inner[:cuts[0]], inner[cuts[0] + 1:cuts[1]], inner[cuts[1] + 1:]
            kind_match = re.fullmatch(r'\s*((?:(?:unsigned|signed)\s+)?\w+)\s*\*\s*', kind)
            if not kind_match or not re.fullmatch(r'\s*(?:' + NUMBER + r')\s*', extra):
                continue
            kind, extra = kind_match[1], int(extra, 0)
        else:
            cast = re.match(r'\*\s*\(\s*((?:(?:unsigned|signed)\s+)?\w+)\s*\*', match.group())
            kind, expr, extra = cast[1], inner, 0
        info = analyze(expr)
        kind = re.sub(r'^(?:unsigned|signed)\s+', lambda m: 'u' if m.group().startswith('un') else 's', kind)
        kind = {'unsignedchar': 'u8', 'signedchar': 's8'}.get(kind.replace(' ', ''), kind)
        if info is None or kind not in WIDTH:
            continue
        base, index, stride, constant = info
        found.append((match.start(), stop, kind, base, index, stride, constant + extra))
        taken = stop
    return found


def _field(offset, kinds):
    suffix = f'{offset:x}'
    return f'm{suffix}' if len(kinds) == 1 else f'u{suffix}'


def _declaration(name, start, stride, members):
    """`struct NAME { char pad[start]; struct { ... } e[1]; };`, members {offset: [kinds]} placed at their offsets."""
    lines, at = [], 0
    for offset in sorted(members):
        kinds = sorted(members[offset])
        width = max(WIDTH[k] for k in kinds)
        if offset > at:
            lines.append(f'char p{at:x}[{offset - at:#x}];')
        if len(kinds) == 1:
            lines.append(f'{kinds[0]} {_field(offset, kinds)};')
        else:
            body = ' '.join(f'{k} {k};' for k in kinds)
            lines.append(f'union {{ {body} }} {_field(offset, kinds)};')
        at = offset + width
    if at < stride:
        lines.append(f'char p{at:x}[{stride - at:#x}];')
    pad = f'char pad[{start:#x}]; ' if start else ''
    return f'struct {name} {{ {pad}struct {{ {" ".join(lines)} }} e[1]; }};\n'


def _groups(accesses, source):
    """{(base, index, stride): (start, {offset: kinds}, [accesses that fit])} for the groups that fit rows."""
    grouped = {}
    for item in accesses:
        grouped.setdefault(item[3:6], []).append(item)
    out = {}
    for key, items in grouped.items():
        stride = key[2]
        start = min(item[6] for item in items) // stride * stride
        fits = [item for item in items
                if 0 <= item[6] - start and item[6] - start + WIDTH[item[2]] <= stride
                and (item[6] - start) % WIDTH[item[2]] == 0]
        if not fits:
            continue
        align = max(WIDTH[item[2]] for item in fits)
        if start % align or stride % align:
            continue
        members = {}
        for item in fits:
            members.setdefault(item[6] - start, set()).add(item[2])
        out[key] = (start, members, fits)
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    definition = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    if not definition:
        return []
    opening = span[0] + definition.end() - 1
    end = close(clean, opening, '{', '}')
    if not end or '#' in clean[opening:end]:
        return []
    groups = _groups(_accesses(source, clean, opening, end), source)
    names = {}
    for (base, index, stride) in groups:
        label = f'__rows_{base}_{stride:x}'
        if label in source:
            continue
        names[(base, index, stride)] = label
    if not names:
        return []

    def build(chosen):
        edits, declared = [], ''
        for key in chosen:
            start, members, fits = groups[key]
            label = names[key]
            declared += _declaration(label, start, key[2], members)
            for begin, stop, kind, base, index, stride, offset in fits:
                field = _field(offset - start, members[offset - start])
                if len(members[offset - start]) > 1:
                    field += f'.{kind}'
                edits.append((begin, stop, f'(((struct {label} *){base})->e[{index}].{field})'))
        edits.sort(reverse=True)
        text = source
        for begin, stop, replacement in edits:
            text = text[:begin] + replacement + text[stop:]
        line = source.rfind('\n', 0, span[0]) + 1
        return text[:line] + declared + text[line:]

    keys = list(names)
    result = [(FAMILY, build(keys))]
    if len(keys) > 1:
        for key in keys[:MAX_CHILDREN]:
            result.append((FAMILY, build([key])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
