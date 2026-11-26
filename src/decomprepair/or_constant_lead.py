"""A packed word's constant written first in its `|` chain (GCC 2.7.2, KMC, N64).

`gfx->w0 = (n << 12) | (((n & 127) << 1) | 0x01000000);` and `gfx->w0 = 0x01000000 | (n << 12) | ((n & 127) << 1);` are the
same value and not the same bytes. The first is grouped as written: the constant joins the low field first, so the first
`or` is the low field's and the constant is held in a register until then (`lui $v0, 0x100` early, `or $v1,$v1,$v0` between
the fields). The second is the chain the game wrote when its macro put the opcode first: `(op) | (a << 12) | b` is
`((op | a<<12) | b)`, the constant joins the shifted field, and the expression's temporaries are born in the other order
(`sll $v1,$a1,12; or $v1,$v1,$v0; andi $v0,$a1,0x7f; sll $v0,$v0,1; or $v1,$v1,$v0`). 805 -> 365 on four such words of a
559-instruction N64 display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`; the rest of the function was
register rows). `or_constant_stage` does the opposite (the constant joins the lower field first); this offers the lead
position, and the groupings between them are `reassociate`'s.

`variants` takes each assignment `lhs = chain;` whose right side is a chain of `|` with one literal constant among
the terms (parenthesised groups of only `|` are part of the chain) that is not first, and writes the chain with the
constant first and the other terms in their order, left-associated. The assignments that become the same text are one
child (the four identical tails of the function above are one step), and one child takes them all.
"""
import re

from .csource import find
from .pattern_repairs import close

FAMILY = 'or_constant_lead'
FAMILIES = (FAMILY,)

_ASSIGN = re.compile(r'(?P<lhs>[A-Za-z_][\w.\->\[\]*]*)(?P<op>\s*=(?!=)\s*)(?P<rhs>[^;{}=]+);')
_CONSTANT = re.compile(r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*')
MAX_CHILDREN = 6


def _python_split_or(text):
    """The terms of a top-level `|` chain in `text` (not `||`), or None when it has no top-level `|`."""
    terms, depth, start = [], 0, 0
    for pos, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == '|' and depth == 0 and text[pos - 1:pos] != '|' and text[pos + 1:pos + 2] != '|':
            terms.append(text[start:pos].strip())
            start = pos + 1
    if not terms:
        return None
    terms.append(text[start:].strip())
    return terms


_split_or = _python_split_or
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split_or(text):
        terms, start = [], 0
        for at in _scan.top_offsets(text, '|', 2):
            if text[at - 1:at] != '|' and text[at + 1:at + 2] != '|':
                terms.append(text[start:at].strip())
                start = at + 1
        if not terms:
            return None
        terms.append(text[start:].strip())
        return terms


def _flatten(text):
    """The terms of an or-chain, a parenthesised group that is itself an or-chain flattened into it."""
    terms = _split_or(text)
    if terms is None:
        stripped = text.strip()
        if stripped.startswith('(') and close(stripped, 0) == len(stripped):
            inner = _split_or(stripped[1:-1])
            if inner is not None:
                return [t for term in inner for t in _flatten(term)]
        return [stripped]
    return [t for term in terms for t in _flatten(term)]


def _apply(source, edits):
    for start, end, new in sorted(edits, reverse=True):
        source = source[:start] + new + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    edits = []
    for hit in _ASSIGN.finditer(text):
        rhs = hit['rhs']
        if re.search(r'[?:]|\|\||&&', rhs) or '|' not in rhs:  # lower precedence than the chain itself
            continue
        terms = _flatten(rhs)
        constants = [i for i, term in enumerate(terms) if _CONSTANT.fullmatch(term)]
        if len(terms) < 2 or len(constants) != 1 or constants[0] == 0:
            continue
        lead = terms.pop(constants[0])
        # a term that is not already a primary keeps its parentheses
        rest = [t if re.fullmatch(r'[\w.\->\[\]]+|\(.*\)', t) and (not t.startswith('(') or close(t, 0) == len(t)) else f'({t})'
                for t in terms]
        new = ' | '.join([lead] + rest)
        if new.replace(' ', '') == rhs.replace(' ', ''):
            continue
        edits.append((span[0] + hit.start('rhs'), span[0] + hit.end('rhs'), new))
    groups = {}
    for start, end, new in edits:
        groups.setdefault(re.sub(r'\s+', '', new), []).append((start, end, new))
    out = [(FAMILY, _apply(source, group)) for group in list(groups.values())[:MAX_CHILDREN - 1]]
    if len(groups) > 1:
        out.append((FAMILY, _apply(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
