"""A later constant assignment moved between a call and the division that uses its result.

`inv = 1.0f / sqrtf(x); ...; zero = 0.0f;` can be, in the game, `inv = sqrtf(x); zero = 0.0f; inv = 1.0f / inv;`: the
constant's load then sits right after the call (here after the `sqrt.s` NaN fallback), and the constant's register is
taken before the ones set later, which moves it and its neighbours to other saved registers. A KMC GCC 2.7.2 `-O1`
function of 428 instructions stood at 285 with only float register rows and one `mtc1 $zero` out of place; the split
with the constant between matched. A search that moves whole statements cannot put one inside another, and one that
splits an expression without moving the constant changes nothing.

One child per pair of a statement `a = <literal> / call(...);` and a following `b = <number>;` in the same straight run
of statements, where nothing between them names `b`. The value is the same; the judge says whether the bytes are.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'constant_between_division'
FAMILIES = (FAMILY,)
LIMIT = 8
ID = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?)[fFuUlL]*'
DIVISION = re.compile(rf'(?<=[;{{}}])(\s*)({ID})\s*=\s*({NUMBER})\s*/\s*({ID})\s*\(')
CONSTANT = re.compile(rf'(?<=;)\s*({ID})\s*=\s*{NUMBER}\s*;')


def variants(source, name):
    """(family, source) for each constant moved between a call and its division; see the module's docstring."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    if re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return []
    opening = clean.find('{', *span)
    out = []
    for hit in DIVISION.finditer(clean, opening, span[1]):
        paren = hit.end() - 1
        end = close(clean, paren)
        if end is None:
            continue
        # `close` answers the offset past the bracket
        tail = re.compile(r'\s*;').match(clean, end)
        if not tail:
            continue
        target, indent = hit[2], hit[1]
        for later in CONSTANT.finditer(clean, tail.end() - 1, span[1]):
            between = clean[tail.end():later.start()]
            if re.search(r'[{}]|\b(?:if|else|for|while|do|switch|case|goto|return)\b|(?<!:):(?!:)', between):
                break
            moved = later[1]
            if moved == target or re.search(rf'\b{moved}\b', between + clean[hit.start():tail.end()]):
                continue
            statement = source[later.start():later.end()].strip()
            call = source[hit.start(4):end]
            numerator = source[hit.start(3):hit.end(3)]
            line = '\n' + indent.rsplit('\n', 1)[-1] if '\n' in indent else ' '
            split = f'{indent}{target} = {call};{line}{statement}{line}{target} = {numerator} / {target};'
            # the moved statement leaves no blank line behind
            before = source[tail.end():later.start()].rstrip()
            out.append((FAMILY, source[:hit.start()] + split + before + source[later.end():]))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
