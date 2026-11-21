"""A product's computed factor held in a local that the function reuses later, so the product's result moves.

`g = lhu * (((a * 0xC00) / 60) * rate >> 3);` compiles the factor into a temporary that dies in the `mult`; the product
then takes that temporary's register ("the result ties to the first operand that dies") and `mflo` writes `$v0` where
the game writes `$v1`, the halfword's register. A local that the function assigns again later (m2c keeps one name for
unrelated values: `h` held the factor and, in the next block, a sum) is a pseudo referenced in two blocks, so
local-alloc leaves it to the global allocator: it no longer ties, the product takes the other factor's register, and
the whole block (chain, `mult`, `mflo`, the stores) came out as the game's. A sequencer function stood at 195 on this
alone; with `h = factor; g = h * lhu;` its first block had no mismatched rows (the same product register was the last
open row of another game's sequencer, never solved by operand order, `*=` or casts).

Offered when `g = A * B;` has one side an expression with an operator and the other a plain load or variable, and a
declared scalar local `h` is first mentioned after the statement, by an assignment that does not read it: `h = A;
g = h * B;` and the factors the other way round. The meaning is unchanged, as `h` is dead at the statement.
"""
import re

from .csource import _blank, find
from .global_pointer_run_repairs import _blocks, _statements
from .pattern_repairs import close

FAMILY = 'product_operand_reuse'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
STATEMENT = re.compile(r'(?P<dest>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;{}=]+?)\s*;')
SCALAR = re.compile(r'(?m)^[ \t]*(?:register\s+)?(?:(?:unsigned|signed)\s+)?(?:long|int|short|char|u8|s8|u16|s16|u32|s32)\s+'
                    r'(' + IDENT + r')\s*;')


def _binary_operators(value):
    """(position, operator) of each binary operator at the top level of an expression."""
    depth, found, position = 0, [], 0
    while position < len(value):
        char = value[position]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and char in '+-*/%&|^<>?:=!':
            operator = value[position:position + 2] if value[position:position + 2] in ('<<', '>>', '&&', '||', '==', '!=',
                                                                                         '<=', '>=') else char
            before = value[:position].rstrip()
            if before and (before[-1] in ')]' or before[-1].isalnum() or before[-1] == '_'):
                found.append((position, operator))
            position += len(operator) - 1
        position += 1
    return found


def _strip(side):
    side = side.strip()
    while side.startswith('(') and close(side, 0) == len(side):
        side = side[1:-1].strip()
    return side


def _compound(side):
    return bool(_binary_operators(_strip(side)))


def _product(value):
    """(left, right) of `A * B` when the multiplication is the whole expression, else None."""
    found = _binary_operators(value)
    if len(found) != 1 or found[0][1] != '*':
        return None
    return value[:found[0][0]].strip(), value[found[0][0] + 1:].strip()


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    locals_ = SCALAR.findall(body)
    result = []
    seen = set()
    for first, last in _blocks(clean, opening, end):
        for start, stop in _statements(clean, first, last):
            hit = STATEMENT.fullmatch(clean, start, stop)
            if not hit or start in seen:
                continue
            seen.add(start)
            value = hit['value']
            pair = _product(value)
            if pair is None:
                continue
            left, right = pair
            if _compound(left) == _compound(right):
                continue
            after = clean[stop:end]
            for staged in locals_:
                word = r'(?<![\w.>])' + staged + r'\b'
                if staged == hit['dest'] or re.search(word, value) or re.search(word, SCALAR.sub('', clean[opening:start])):
                    continue
                follow = re.search(word, after)
                if not follow or not re.match(r'\s*=(?!=)', after[follow.end():]):
                    continue
                assigned = re.match(r'\s*=(?!=)\s*([^;]*);', after[follow.end():])
                if not assigned or re.search(word, assigned[1]):
                    continue
                factor, other = (left, right) if _compound(left) else (right, left)
                for product in (f'{staged} * {other}', f'{other} * {staged}'):
                    text = f'{source[:start]}{staged} = {factor}; {hit["dest"]} = {product};{source[stop:]}'
                    if (FAMILY, text) not in result:
                        result.append((FAMILY, text))
    return result
