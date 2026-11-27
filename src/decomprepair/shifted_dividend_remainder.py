"""m2c's remainder of a shifted dividend, read as a division of the unshifted value, back as `(x >> k) % n`.

GCC divides `x >> k` (signed) by a constant that is no power of two with `mult` by a magic number, and takes the sign
correction from `x` itself: the sign of `x >> k` is the sign of `x`, so `(x >> k) >> 31` folds to `x >> 31`. m2c then sees
a `sra 31` of `x` beside the high word and reads the quotient as `x / (n << k)`, while the multiplicand is still `x >> k`:

    p->frame = (p->tick >> 1) - ((p->tick / 10) * 5);      /* the target computes (p->tick >> 1) % 5 */
    p->id = base + ((next >> 1) - (((count + 1) / 14) * 7));   /* next = count + 1: (next >> 1) % 7 */

The draft is not the program (for a negative value `x / 10 != (x >> 1) / 5`), and it shifts the second quotient by one
more bit and moves the `mult` and its registers. On a 94-instruction N64 object update (SN64 GCC 2.8.1,
`-G0 -mips3 -O2`) the saved best scored 705 and writing both sites as `%` was exact (705 -> 0).

An unsigned dividend comes out the same way through `multu`, with a further shift left outside the quotient:
`h = x / 6; ... (x >> 2) - ((h >> 3) * 0xC)` is `(x >> 2) % 12` (6 << 3 == 12 << 2). On a 92-instruction N64 object
update (same compiler, `-G0 -mips3 -O2`) that site alone took the machine draft from 1045 to 230.

Shape: `A - P * N` where A is `X >> k`, P is `Y / M` (or `(Y / M0) >> s` with `M == M0 << s`), `M == N << k`, N no power of two, and Y is X (the same text, casts
aside), or one of them is a local assigned once with the other. A, the product and the quotient may each sit in such a
local. Children: every site written `A' % N` at once, then each site alone. The judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'shifted_dividend_remainder'
FAMILIES = (FAMILY,)
LIMIT = 8
_SIGNED_CAST = re.compile(r'\(\s*(?:s32|int|signed\s+int)\s*\)\s*')


_TOKENS = {operator: re.compile(r'[(\[{)\]}]|' + pattern) for operator, pattern in (
    ('-', r'(?<!-)-(?![->=])'), ('>>', r'>>(?!=)'), ('*', r'\*(?!=)'), ('/', r'/(?!=)'))}
_OTHER = re.compile(r'\+|<<|&|\||\^|\?|,|==|<=|!=|&&')


def _top(text, operator):
    """The positions of a binary `operator` of `text` that stands outside every bracket."""
    depth, out = 0, []
    for hit in _TOKENS[operator].finditer(text):
        token = hit.group()
        if token in '([{':
            depth += 1
        elif token in ')]}':
            depth -= 1
        elif depth == 0:
            before = text[:hit.start()].rstrip()
            # not a unary use or a cast's operand
            if re.search(r'[\w\])]$', before) and not _SIGNED_CAST.fullmatch(before):
                out.append(hit.start())
    return out


def _mixed(text):
    """Whether another binary operator stands outside every bracket of `text`."""
    outer, count = text, 1
    while count:
        outer, count = re.subn(r'\([^()]*\)|\[[^\[\]]*\]', '_', outer)
    return bool(_OTHER.search(outer.replace('->', '.')))


def _unwrapped(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _operand(text):
    """`text` without brackets and signed casts around the whole of it."""
    text = _unwrapped(text)
    while True:
        cast = _SIGNED_CAST.match(text)
        if not cast:
            return text
        text = _unwrapped(text[cast.end():])


def _key(text):
    return re.sub(r'\s+', '', _SIGNED_CAST.sub('', _operand(text)))


def _definition(body, name):
    """The right side of a local assigned exactly once by a plain statement, else None."""
    if not re.fullmatch(IDENT, name):
        return None
    writes = re.findall(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{name}\b|'
                        rf'(?<![\w.>]){name}\s*(?:\+\+|--)|&\s*{name}\b(?!\s*[.\[])', body)
    if len(writes) != 1:
        return None
    hit = re.search(rf'(?<![\w.>]){name}\s*=(?!=)\s*([^;{{}}]+);', body)
    return hit[1] if hit else None


def _binary(body, text, operator):
    """(left, right) of the last top-level `operator` of `text`, looking through one local that holds it."""
    for candidate in (_operand(text), _definition(body, _operand(text))):
        if candidate is None:
            continue
        candidate = _operand(candidate)
        places = _top(candidate, operator)
        if places:
            return candidate[:places[-1]].strip(), candidate[places[-1] + len(operator):].strip()
    return None


def _number(text):
    text = _unwrapped(text)
    return int(text.rstrip('uUlL'), 0) if re.fullmatch(NUMBER, text) else None


_FIELD_CAST = re.compile(r'\(\s*(u8|u16|u32)\s*\)\s*(?=M2C_FIELD\s*\([^;]*?,\s*\1\s*\*\s*,)')


def _same(body, left, right):
    # a cast to the type the field already has (`(u8) M2C_FIELD(p, u8 *, 9)`) is the field itself
    keys = [{_key(_FIELD_CAST.sub('', _operand(value)))} for value in (left, right)]
    for found, value in zip(keys, (left, right)):
        defined = _definition(body, _operand(value))
        if defined is not None:
            found.add(_key(_FIELD_CAST.sub('', _operand(defined))))
    return bool(keys[0] & keys[1])


def _quotient(body, text):
    """(dividend, divisor) of the quotient `text`: `Y / M`, or `(Y / M0) >> s`, which m2c leaves of an unsigned
    division whose magic multiply it read with a smaller shift (`M == M0 << s`)."""
    division = _binary(body, text, '/')
    if division:
        return division[0], _number(division[1])
    shift = _binary(body, text, '>>')
    if shift:
        bits, division = _number(shift[1]), _binary(body, shift[0], '/')
        if division and bits is not None and 0 < bits < 16 and (divisor := _number(division[1])):
            return division[0], divisor << bits
    return None


def _site(body, text):
    """The `A % N` that `text` (a whole expression) stands for, else None."""
    places = _top(text, '-')
    if len(places) != 1 or _mixed(text):
        return None
    left, right = text[:places[0]].strip(), text[places[0] + 1:].strip()
    shift = _binary(body, left, '>>')
    product = _binary(body, right, '*')
    if not shift or not product or re.search(r'\b(?:u32|unsigned)\b', left):
        return None
    bits = _number(shift[1])
    if bits is None or not 0 < bits < 16:
        return None
    for quotient, factor in (product, product[::-1]):
        divisor = _number(factor)
        if divisor is None or divisor < 3 or not divisor & (divisor - 1):
            continue
        division = _quotient(body, quotient)
        if not division or division[1] != divisor << bits or not _same(body, shift[0], division[0]):
            continue
        kept = _unwrapped(left)
        if not re.fullmatch(IDENT, kept):
            kept = f'({kept})'
        return f'{kept} % {divisor}'
    return None


def _spans(clean, opening, end):
    """Every place a whole expression can stand: inside brackets, and right of a plain assignment or `return`."""
    for at in range(opening + 1, end):
        if clean[at] == '(':
            stop = close(clean, at, '(', ')')
            if stop:
                yield at + 1, stop - 1
    for hit in re.finditer(r'(?:(?<![=!<>+\-*/%&|^])=(?!=)|\breturn\b)\s*([^;{}=]+);', clean[opening:end]):
        yield opening + hit.start(1), opening + hit.end(1)


def variants(source, name):
    part = view(source, name)
    if not part or '>>' not in part.body or '/' not in part.body:
        return []
    clean, body = part.clean, part.body
    sites = []
    for start, stop in _spans(clean, part.opening, part.end):
        written = _site(body, clean[start:stop].strip())
        if written is None or any(start < b and a < stop for a, b, _ in sites):
            continue
        sites.append((start, stop, written))
        if len(sites) == LIMIT:
            break
    if not sites:
        return []
    out = [edit(source, sites)]
    if len(sites) > 1:
        out += [edit(source, [one]) for one in sites]
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
