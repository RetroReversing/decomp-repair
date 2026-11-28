"""A round-up to a variable power of two, written as steps in the destination's own register.

    low = ((u32) (D - 1 + (1 << align)) >> align) << align;      low = D;
                                                          ->     low += (1 << align) - 1;
                                                                 low >>= align;
                                                                 low <<= align;

The same program, but the one expression keeps every step in temporaries of its own (and fold moves the `- 1` onto
the `1 << align` side or leaves the destination dying twice, which hands it to global allocation), while the steps keep
the whole chain in the destination's register. A 22-instruction N64 bump allocator (SN64 GCC 2.8.1,
`-G0 -mips3 -O2 -mfp64`) went from 265 with the one expression to 0 with these statements: `addiu`, `addu`, `srlv`,
`sllv` all on one register. One function; the register account is a hypothesis, the judge decides.
`round_up_in_steps` handles only a constant shift of the variable itself.

`variants` finds `X = ((E) >> N) << N;` where `N` is a name, `E` is `A - 1 + (1 << N)` in any order of those terms (or
`A + ((1 << N) - 1)`), and the right shift is unsigned (a `(u32)` cast, or `A` is `X` itself and `X` is declared `u32`).
`X = A;` is left out when `A` is `X`. One child with every such statement, and one per statement.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'align_up_in_steps'
FAMILIES = (FAMILY,)
LIMIT = 6
STATEMENT = re.compile(rf'(?<=[;{{}}:])(?P<lead>\s*)(?P<x>{IDENT})\s*=(?!=)\s*(?P<rhs>[^;{{}}=]+);')
CAST = re.compile(r'\(\s*u32\s*\)\s*')
EFFECT = re.compile(rf'\+\+|--(?!>)|\?|,|\b(?!(?:sizeof|u32|s32)\b){IDENT}\s*\(')


def _closing(text, opening):
    depth = 0
    for index in range(opening, len(text)):
        depth += {'(': 1, ')': -1}.get(text[index], 0)
        if not depth:
            return index
    return -1


def _strip(text):
    """`text` without the parentheses around all of it and the `(u32)` casts in front; whether a cast was there."""
    text, cast = text.strip(), False
    while True:
        hit = CAST.match(text)
        if hit:
            rest = text[hit.end():].strip()
            # the cast covers the whole expression only when one parenthesized group follows it
            if not rest.startswith('(') or _closing(rest, 0) != len(rest) - 1:
                return text, cast
            text, cast = rest, True
        elif text.startswith('(') and _closing(text, 0) == len(text) - 1:
            text = text[1:-1].strip()
        else:
            return text, cast


def _top(text, operator):
    """The offsets of `operator` outside every bracket."""
    depth, found = 0, []
    for index, char in enumerate(text):
        depth += {'(': 1, '[': 1, ')': -1, ']': -1}.get(char, 0)
        if not depth and text.startswith(operator, index):
            found.append(index)
    return found


def _shift(text, operator, count=None):
    places = _top(text, operator)
    if not places:
        return None
    left, right = text[:places[-1]].strip(), text[places[-1] + 2:].strip()
    if not re.fullmatch(IDENT, right) or (count and right != count):
        return None
    return left, right


def _terms(text):
    """[(sign, term)] of a top-level sum, or nothing when another operator of lower rank is in it."""
    terms, depth, start, sign = [], 0, 0, '+'
    for index, char in enumerate(text):
        depth += {'(': 1, '[': 1, ')': -1, ']': -1}.get(char, 0)
        if depth or char not in '+-' or text[index:index + 2] == '->' or not text[start:index].strip():
            continue
        terms.append((sign, text[start:index].strip()))
        sign, start = char, index + 1
    terms.append((sign, text[start:].strip()))
    loose = re.sub(r'->', '.', text)
    while re.search(r'\([^()]*\)|\[[^\[\]]*\]', loose):
        loose = re.sub(r'\([^()]*\)|\[[^\[\]]*\]', 'v', loose)
    return [] if re.search(r'<<|>>|[<>&|^=!]', loose) else terms


def _base(expr, count):
    """`A` when `expr` is `A + (1 << count) - 1`, else nothing."""
    power = re.compile(rf'1\s*<<\s*{count}')
    left, ones, powers, masks = [], 0, 0, 0
    for sign, term in _terms(expr):
        inner = _strip(term)[0]
        parts = _terms(inner) if term.startswith('(') else []
        if sign == '+' and term.startswith('(') and power.fullmatch(inner):
            powers += 1
        elif sign == '-' and term in ('1', '1U', '1u'):
            ones += 1
        elif (sign == '+' and len(parts) == 2 and parts[1] in (('-', '1'), ('-', '1U'))
              and power.fullmatch(_strip(parts[0][1])[0])):
            masks += 1
        else:
            left.append((sign, term))
    if (ones, powers, masks) not in ((1, 1, 0), (0, 0, 1)) or not left or left[0][0] != '+':
        return None
    return ' '.join([left[0][1]] + [f'{sign} {term}' for sign, term in left[1:]])


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    edits = []
    for hit in STATEMENT.finditer(clean, part.opening, part.end):
        x, rhs = hit['x'], source[hit.start('rhs'):hit.end('rhs')]
        outer, first = _strip(rhs)
        up = _shift(outer, '<<')
        if not up:
            continue
        shifted, second = _strip(up[0])
        down = _shift(shifted, '>>', up[1])
        if not down:
            continue
        count = up[1]
        summed, third = _strip(down[0])
        inner = CAST.match(down[0])
        base = _base(summed, count)
        if base is None or x == count or EFFECT.search(base):
            continue
        unsigned = bool(re.search(rf'\bu32\s+(?:[^;(){{}}*]*,\s*)?{x}\b', clean[:hit.start()]))
        same = _strip(base)[0] == x
        if not (second or third or inner or (same and unsigned)):
            continue
        start = hit.start('x')
        line = source.rfind('\n', 0, start) + 1
        indent = source[line:start]
        joint = f'\n{indent}' if not indent.strip() else ' '
        down_step = f'{x} >>= {count};' if unsigned else f'{x} = (u32) {x} >> {count};'
        steps = [] if same else [f'{x} = {_strip(base)[0]};']
        steps += [f'{x} += (1 << {count}) - 1;', down_step, f'{x} <<= {count};']
        edits.append((start, hit.end(), joint.join(steps)))
    out = [(FAMILY, edit(source, [one])) for one in edits[:LIMIT]]
    if len(edits) > 1:
        out.insert(0, (FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}
