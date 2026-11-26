"""A product by a constant wider than 32 bits whose low bits are all zero: `e * (K << n)` as `(e * K) << n`.

Observed (GCC 2.7.2 SN/KMC `-G0 -mips3 -O2`; one function that scales an address offset with a shift-and-add chain,
215 -> 0): m2c reads the 64-bit constant the shift-and-add chain implies and writes

    return (s32) ((arg0 - (s32) &D_801D9220) * -0x22222222000) >> 0x10;       /* draft */
    return (s32) (((arg0 - (s32) &D_801D9220) * -0x11111111) << 13) >> 16;   /* target */

The product is 32-bit in this game, so only the low 32 bits of `e * K` exist and `e * (K' << n)` equals
`(e * K') << n` for every `e`. The two are the same value, but a constant above 32 bits is not one the compiler's
multiply expander can decompose into the chain it emitted, while a 32-bit constant times a shift is: the draft judged
215 and the spelling with the shift 0. Hypothesis (not confirmed in the compiler's source): the expander's cost search
works on the constant's low word, and a wide literal is reduced before that.

Children: every product `e * K` (or `K * e`, the literal optionally negated) whose literal is wider than 32 bits and
has trailing zero bits, written `((e * K') << n)` with `n` all the trailing zeros and, when a smaller shift also
brings the constant under 32 bits, that spelling too. The parentheses are left out when the product already stands
in its own group. The operand has no call, assignment, `++`/`--`, comparison or volatile name, and nothing declared
float. Proposals only; the judge decides."""
import re

from decomprepair.product_split_sum import (
    _FLOAT_DECL,
    _NUM,
    _VOLATILE,
    _operand_after,
    _operand_before,
    _prev_char,
    _pure,
)

FAMILIES = ('wide_constant_shift_split',)
FAMILY = FAMILIES[0]
LIMIT = 12
_LITERAL = re.compile(r'\s*(-\s*)?(' + _NUM + r')(?![\w.])')
_AFTER_LITERAL_BAD = re.compile(r'\s*(?:[.(\[\w]|\*=)')
_FLOAT_TOKEN = re.compile(r'\b(?:f32|f64|float|double)\b|\d\.\d|\d[fF]\b')
_UNARY_OK = set('(,=<>?:[{;}|^!~+-*') | {''}


def _mask(source):
    def blank(m):
        return re.sub(r'[^\n]', ' ', m[0])
    text = re.sub(r'/\*.*?\*/|//[^\n]*', blank, source, flags=re.S)
    return re.sub(r'(?m)^[ \t]*#(?:[^\n\\]|\\\n)*', blank, text)


def _shifts(value):
    """The shift counts that bring the literal's magnitude to 32 bits or fewer, largest first; [] when it is not wide
    or has no trailing zero bit."""
    magnitude = abs(value)
    if magnitude <= 0xFFFFFFFF:
        return []
    zeros = (magnitude & -magnitude).bit_length() - 1
    need = magnitude.bit_length() - 32
    options = [zeros] + ([need] if 1 <= need < zeros else [])
    return [n for n in options if 1 <= n <= 31 and (magnitude >> n) <= 0xFFFFFFFF]  # 32 or more is undefined in C


def _spell(literal_text, negative, value, shift):
    reduced = abs(value) >> shift
    digits = hex(reduced) if literal_text.lower().startswith('0x') else str(reduced)
    return ('-' if negative else '') + digits


def _sites(text, floats, volatiles):
    found = {}

    def add(a, b, operand, literal_text, negative, value):
        shifts = _shifts(value)
        if shifts and _pure(operand, floats, volatiles) and not _FLOAT_TOKEN.search(operand):
            found.setdefault((a, b), (a, b, operand.strip(), literal_text, negative, value, shifts))

    for m in re.finditer(r'(?<![*=/<>&|^+\-%!])\*(?![*=])', text):
        star = m.start()
        lit = _LITERAL.match(text, star + 1)
        span = _operand_before(text, star)
        if lit and span and not _AFTER_LITERAL_BAD.match(text, lit.end()):
            add(span[0], lit.end(), text[span[0]:span[1]], lit[2], bool(lit[1]), int(lit[2], 0))
        # K * e
        char, i = _prev_char(text, star)
        before = re.search(r'(?<![\w.])(-\s*)?(' + _NUM + r')$', text[:i + 1]) if char.isalnum() else None
        right = _operand_after(text, star + 1)
        if before and right and not re.match(r'\s*[.(\[]', text[right[1]:]):
            start = before.start()
            prev, _ = _prev_char(text, start)
            if prev in _UNARY_OK or text[:start].rstrip().endswith('return'):
                add(start, right[1], text[right[0]:right[1]], before[2], bool(before[1]), int(before[2], 0))
    return sorted(found.values())


def _enclosed(text, a, b):
    left, _ = _prev_char(text, a)
    right = re.compile(r'\s*(.)').match(text, b)
    return left == '(' and bool(right) and right[1] == ')'


def _apply(source, text, group, rank):
    out = source
    for a, b, operand, literal_text, negative, value, shifts in sorted(group, reverse=True):
        shift = shifts[rank]
        product = f'{operand} * {_spell(literal_text, negative, value, shift)}'
        body = f'({product}) << {shift}'
        out = out[:a] + (body if _enclosed(text, a, b) else f'({body})') + out[b:]
    return out


def variants(source, name=None, header=None):
    text = _mask(source)
    floats = set(_FLOAT_DECL.findall((header or '') + '\n' + text))
    volatiles = set(_VOLATILE.findall((header or '') + '\n' + text))
    sites = _sites(text, floats, volatiles)
    kids = []
    for rank in range(2):
        chosen = [s for s in sites if len(s[6]) > rank]
        kids += [_apply(source, text, [s], rank) for s in chosen]
        if len(chosen) > 1:
            kids.append(_apply(source, text, chosen, rank))
    unique = list(dict.fromkeys(kids))
    return [(FAMILY, s) for s in unique if s != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
