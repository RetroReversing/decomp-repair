"""The order and grouping of an address sum: `(table + a + b)[i]` and `[a + b]`.

GCC 2.7.2 keeps a sum in the shape the source gave it: `(base + (x >> 7) + n)[i]` is `(base + x') + n`, and combine or
loop.c then see the `n` term apart from the first two, split a scaled term (`n * 2`) off to be hoisted (and, when the
registers run out, spilled), where `(base + ((x >> 7) + n))[i]` adds the two integers first and scales the sum once.
And the two operands of an index sum are evaluated left to right, so `[(x >> 7) + (v & mask)]` and
`[(v & mask) + (x >> 7)]` put the shifted value in a different temporary and a different register. m2c writes the
sums as it meets them, which is rarely the way the game's author did.

Two families, each a child per site:

  pointer_sum_regroup  `(P + A + B)[i]` -> `(P + (A + B))[i]`, for a pointer-or-array name P and two terms.
  index_sum_swap       `[A + B]` -> `[B + A]`, for a subscript of exactly two `+` terms that read no state a swap
                       could reorder (no assignment, increment or call in either term).

Found by hand on a 681-instruction bit-stream decoder, KMC gcc 2.7.2: the regrouped sum took a function from 3775 to
2627 (its scaled `n * 2` was hoisted and spilled), and the swapped index sum, with the operand order the target's temporaries show, from
11781 to 11371 (docs/learnings/function/bit-stream-decoder-table-loops-and-register-roles.md). The judge decides each.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('pointer_sum_regroup', 'index_sum_swap')


def _terms(text):
    """`text` split on its top-level `+` (not inside brackets), as (start, end) spans; None for a top-level `-`."""
    depth, spans, start = 0, [], 0
    for at, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0 and char == '+' and text[at - 1:at] != '+' and text[at + 1:at + 2] not in ('+', '='):
            spans.append((start, at))
            start = at + 1
        elif depth == 0 and char == '-' and text[at - 1:at] != '-' and text[at + 1:at + 2] not in ('-', '=', '>'):
            return None  # a difference: the grouping is not free
    spans.append((start, len(text)))
    return spans


def _quiet(text):
    """A term a swap or regroup cannot reorder: it reads values and assigns nothing."""
    return not re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\w\s*\(', text)


def _subscripts(clean, begin, end):
    """(open, close) of each `[...]` in the body, with the position of its `(`... group when it has one."""
    pos = begin
    while True:
        at = clean.find('[', pos, end)
        if at < 0:
            return
        stop = close(clean, at, '[', ']')
        if stop:
            yield at, stop - 1
        pos = at + 1


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    for opening, closing in _subscripts(clean, part.opening + 1, part.end):
        inner = clean[opening + 1:closing]
        spans = _terms(inner)
        if spans is not None and len(spans) == 2 and all(_quiet(inner[a:b]) for a, b in spans):
            (a, b), (c, d) = spans
            swapped = inner[c:d].strip() + ' + ' + inner[a:b].strip()
            if swapped != inner.strip():
                out.append(('index_sum_swap', edit(source, [(opening + 1, closing, swapped)])))
        # the group before the `[`: (P + A + B)[...]
        if opening > 0 and clean[opening - 1] == ')':
            depth, at = 0, opening - 1
            while at >= part.opening:
                depth += (clean[at] == ')') - (clean[at] == '(')
                if depth == 0:
                    break
                at -= 1
            group = clean[at + 1:opening - 1]
            gspans = _terms(group)
            if gspans is None or len(gspans) != 3 or not all(_quiet(group[a:b]) for a, b in gspans):
                continue
            (a, b), (c, d), (e, f) = gspans
            if not re.fullmatch(IDENT, group[a:b].strip()):
                continue
            regrouped = f'{group[a:b].strip()} + ({group[c:d].strip()} + {group[e:f].strip()})'
            out.append(('pointer_sum_regroup', edit(source, [(at + 1, opening - 1, regrouped)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
