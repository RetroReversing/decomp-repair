"""A chain storing one literal, `a = b = K;`, with its two targets exchanged: `b = a = K;`.

A chain stores its innermost target first, and GCC also sets up the two addresses in an order that follows the text, so
the two spellings differ in both. A chain written from separate statements keeps one of the two orders
(`constant_store_chain`); a chain that is already there had no rewrite for the other. Measured with SN GCC 2.8.1
(`-G0 -mips3 -O2 -mfp64`) on a 23-instruction N64 fill loop storing 0xFFFF into two buffers: 40 one way, 0 the other.

Offered for each statement of the shape `lvalue = lvalue = literal;` (no call, `++`, `--` or compound operator in
either target, and the targets differ), at most `LIMIT`. Both stores store the literal in either order, so only the
order of the two writes changes; a function with `volatile` is left alone. Proposals only; the judge decides.
"""
import re

from .integer_repair_support import view

FAMILY = 'constant_chain_swap'
FAMILIES = (FAMILY,)
LIMIT = 8
_LVALUE = r'[*(\w][^;{}=!<>?]*?(?:->[^;{}=!<>?]*?)*'
_CHAIN = re.compile(rf'(?<=[;{{}}])(?P<gap>\s*)(?P<first>{_LVALUE})(?<![-+*/%&|^\s])(?P<one>\s*=\s*)'
                    rf'(?P<second>{_LVALUE})(?<![-+*/%&|^\s])(?P<two>\s*=\s*)'
                    r'(?P<value>-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+f?)?)[uUlL]*)\s*;')


def variants(source, name):
    """Each two-target literal chain with its targets exchanged."""
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean[part.opening:part.end]):
        return []
    children = []
    for hit in _CHAIN.finditer(part.clean, part.opening, part.end):
        first = source[hit.start('first'):hit.end('first')]
        second = source[hit.start('second'):hit.end('second')]
        if first == second or any(
                '++' in text or '--' in text or text.count('(') != text.count(')')
                or re.search(r'\b(?!(?:if|sizeof|M2C_FIELD)\b)[A-Za-z_]\w*\s*\(', text)
                or re.match(r'(?:else|return|case|do|if|while|for)\b', text) for text in (first, second)):
            continue
        child = (source[:hit.start('first')] + second + source[hit.end('first'):hit.start('second')] + first
                 + source[hit.end('second'):])
        children.append((FAMILY, child))
        if len(children) == LIMIT:
            break
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 57}
