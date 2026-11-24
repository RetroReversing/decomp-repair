"""An equality test of two locals written the other way round: `if (x == y)` as `if (y == x)`.

KMC GCC 2.7.2 (`-O2`, N64) emits `bne`/`beq` with the operands in the order the comparison was expanded, and the
order in which the two values' pseudos are met decides their allocation where nothing else does. In a sound-sequence
interpreter's slot-ownership helper (the two values set in both arms of an `if`, then compared), `y == x` gave the
target's `bne $v1, $v0`, 2515 -> 2510 on a 1315-instruction function. The same program: `==` and `!=` commute.

Rewrites `A == B` and `A != B` inside an `if`/`while` condition when both operands are plain identifiers (locals,
parameters or globals). Bounded to `LIMIT` children, one site each, in text order (the source's own function and
the inline helpers before it).
"""
import re

from .integer_repair_support import IDENT

FAMILY = 'equality_operand_swap'
FAMILIES = (FAMILY,)
LIMIT = 12
_TEST = re.compile(rf'\b(?:if|while)\s*\(\s*(?P<a>{IDENT})\s*(?P<op>==|!=)\s*(?P<b>{IDENT})\s*\)')
_KEYWORDS = {'sizeof', 'return', 'if', 'while'}


def variants(source, name, header=''):
    out = []
    for found in _TEST.finditer(source):
        a, b = found['a'], found['b']
        if a == b or a in _KEYWORDS or b in _KEYWORDS:
            continue
        child = source[:found.start('a')] + b + source[found.end('a'):found.start('b')] + a + source[found.end('b'):]
        out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
