"""m2c's `MULT_HI`/`MULTU_HI` that it did not read as a division, back as `x / d`.

m2c names the high word of a multiply `MULT_HI(x, magic)` when it cannot tell which division the compiler's magic number
stands for, and leaves the shift and sign correction beside it:

    hi = MULT_HI(v, 0x80010003);
    r = ((s32) (hi + v) >> 0xE) - (v >> 0x1F);          /* v / 32767 */

The draft calls a function that does not exist. The divisor follows from the magic number and the shift: `d` is the
whole number nearest `2^(32 + s) / magic`, kept only when `magic` is what a compiler would derive for it. On a
67-instruction N64 routine (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) writing the division was one of the steps from the
draft to an exact match (1899 -> 1484 alone).

Shapes: signed `(h >> s) - (x >> 31)` (or `+ ((u32) x >> 31)`) where `h` is the high word, or the high word plus `x`
for a magic with its top bit set; unsigned `hu >> s`, and `(((u32) (x - hu) >> 1) + hu) >> s` for a 33-bit magic.
`hi` may be a local assigned once. Children: every site at once, then each site alone. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .shifted_dividend_remainder import _definition, _number, _spans, _unwrapped

FAMILY = 'magic_high_divide'
FAMILIES = (FAMILY,)
LIMIT = 8
_CALL = re.compile(r'(?P<kind>MULTU?_HI)\s*\(')
_CASTS = re.compile(r'\(\s*(?:[su]32|int|unsigned(?:\s+int)?|signed(?:\s+int)?)\s*\)\s*')


def _bare(text):
    """`text` without brackets and word casts around the whole of it."""
    text = _unwrapped(text)
    while True:
        cast = _CASTS.match(text)
        if not cast or not text[cast.end():]:
            return text
        rest = text[cast.end():]
        if not (re.fullmatch(IDENT, rest) or rest.startswith('(') and close(rest, 0, '(', ')') == len(rest)
                or _CALL.match(rest)):
            return text
        text = _unwrapped(rest)


def _key(text):
    return re.sub(r'\s+', '', _CASTS.sub('', _bare(text)))


_TOKENS = {operator: re.compile(r'[(\[{)\]}]|' + pattern) for operator, pattern in (
    ('-', r'(?<!-)-(?![->=])'), ('+', r'(?<!\+)\+(?![+=])'), ('>>', r'>>(?!=)'))}


def _split(text, operator):
    """(left, right) of the last binary `operator` of `text` outside every bracket, else None."""
    depth, place = 0, None
    for hit in _TOKENS[operator].finditer(text):
        token = hit.group()
        if token in '([{':
            depth += 1
        elif token in ')]}':
            depth -= 1
        elif not depth:
            before = text[:hit.start()].rstrip()
            # not a unary use or a cast's operand
            if re.search(r'[\w\])]$', before) and not _CASTS.fullmatch(before):
                place = hit
    if place is None:
        return None
    return text[:place.start()].strip(), text[place.end():].strip()


def _high(body, text):
    """(kind, x, magic, local) of the high word `text` stands for, else None."""
    text = _bare(text)
    local = None
    if re.fullmatch(IDENT, text):
        local, text = text, _definition(body, text)
        if text is None:
            return None
        text = _bare(text)
    call = _CALL.match(text)
    if not call or close(text, call.end() - 1, '(', ')') != len(text):
        return None
    inner = text[call.end():-1]
    comma = inner.rfind(',')
    magic = _number(inner[comma + 1:].strip().lstrip('(').rstrip(')')) if comma > 0 else None
    if magic is None:
        return None
    return call['kind'], inner[:comma].strip(), magic & 0xFFFFFFFF, local


def _divisor(magic, bits):
    """The divisor whose magic number over `2^bits` is `magic`, else None."""
    if magic < 1 << 28:  # a compiler's magic uses the word: a small constant is a real fixed-point multiply
        return None
    d = round((1 << bits) / magic)
    if d < 3 or d >= 1 << 31 or not d & (d - 1) or abs(magic * d - (1 << bits)) >= d:
        return None
    return d


def _shift(text):
    """(operand, amount) of `text`, 0 when it is not a shift."""
    shift = _split(_unwrapped(text), '>>')
    if shift and (amount := _number(shift[1])) is not None and amount < 32:
        return shift[0], amount
    return text, 0


def _signed(body, text):
    for operator in ('-', '+'):
        parts = _split(text, operator)
        if not parts:
            continue
        quotient, sign = parts
        sign = _split(_unwrapped(sign), '>>')
        if not sign or _number(sign[1]) != 31 or (operator == '+') != bool(re.match(r'\(\s*(?:u32|unsigned)', sign[0])):
            continue
        dividend = _key(sign[0])
        value, amount = _shift(quotient)
        value = _bare(value)
        added = _split(value, '+')
        if added:
            for high, other in (added, added[::-1]):
                found = _high(body, high)
                if (found and found[0] == 'MULT_HI' and found[2] >= 1 << 31 and _key(found[1]) == _key(other)
                        and _key(other) == dividend and (d := _divisor(found[2], 32 + amount))):
                    return found[1], d, found[3], False
        found = _high(body, value)
        if (found and found[0] == 'MULT_HI' and found[2] < 1 << 31 and _key(found[1]) == dividend
                and (d := _divisor(found[2], 32 + amount))):
            return found[1], d, found[3], False
    return None


def _unsigned(body, text):
    value, amount = _shift(text)
    found = _high(body, value)
    if found and found[0] == 'MULTU_HI' and (d := _divisor(found[2], 32 + amount)):
        return found[1], d, found[3], True
    added = _split(_bare(value), '+')
    if added:
        for halved, high in (added, added[::-1]):
            found = _high(body, high)
            half = _split(_unwrapped(halved), '>>')
            if not found or found[0] != 'MULTU_HI' or not half or _number(half[1]) != 1:
                continue
            difference = _split(_bare(half[0]), '-')
            if (difference and _key(difference[0]) == _key(found[1])
                    and (d := _divisor((1 << 32) + found[2], 33 + amount))):
                return found[1], d, found[3], True
    return None


def _written(site, text):
    dividend, divisor, _local, unsigned = site
    dividend = _unwrapped(dividend)
    if not re.fullmatch(rf'{IDENT}(?:\(\))?', dividend):
        dividend = f'({dividend})'
    if unsigned:
        dividend = f'(u32) {dividend}'
    return f'{dividend} / {divisor}'


def _without_dead(source, name, locals_):
    """The source without the assignments (and declarations) of high-word locals nothing reads any more."""
    for local in locals_:
        part = view(source, name)
        if not part:
            break
        word = rf'(?<![\w.>]){local}\b'
        assigned = [hit for hit in re.finditer(rf'(?m)^[ \t]*{local}\s*=(?!=)[^;\n]*;[ \t]*\n', part.clean)
                    if part.opening < hit.start() < part.end]
        declared = [hit for hit in re.finditer(rf'(?m)^[ \t]*(?:[su]32|int|unsigned int)\s+{local}\s*;[ \t]*\n', part.clean)
                    if part.opening < hit.start() < part.end]
        uses = len(re.findall(word, part.body))
        if len(assigned) == 1 and len(declared) == 1 and uses == 2:
            source = edit(source, [(hit.start(), hit.end(), '') for hit in assigned + declared])
    return source


def variants(source, name):
    part = view(source, name)
    if not part or not _CALL.search(part.body):
        return []
    clean, body = part.clean, part.body
    sites = []
    for start, stop in _spans(clean, part.opening, part.end):
        text = clean[start:stop].strip()
        if '>>' not in text and not _CALL.search(text) and not re.search(r'[A-Za-z_]', text):
            continue
        site = _signed(body, text) or _unsigned(body, text)
        if site is None or any(start < b and a < stop for a, b, *_ in sites):
            continue
        sites.append((start, stop, _written(site, text), site[2]))
        if len(sites) == LIMIT:
            break
    if not sites:
        return []

    def child(chosen):
        out = edit(source, [(a, b, text) for a, b, text, _ in chosen])
        return _without_dead(out, name, dict.fromkeys(local for *_, local in chosen if local))

    out = [child(sites)]
    if len(sites) > 1:
        out += [child([one]) for one in sites]
    return [(FAMILY, text) for text in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 10}
