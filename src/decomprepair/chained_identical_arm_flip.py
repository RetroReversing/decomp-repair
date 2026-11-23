"""chained_identical_arm_flip: `if (C) { X } else if (D) { Y } else { Y }` written as one two-way branch, either polarity.

A search-made draft keeps an `else if (helper())` whose two arms are the same statements (an identity inline helper that
only exists to give the second test a label); alone, collapsing it is neutral. It matters because the branch after it is
laid out by the way the C is written (`branch_polarity`): `if (!(g & 1)) { +9 } else { +1 }` makes the compiler's delay-slot
filler (reorg) take the +1 arm's first insn from the branch target (`bnel`), while `if (g & 1) { +1 } else { +9 }` leaves it
the `beqz` + `j` of the target. Measured on one 118-instruction KMC (gcc-2.7.2 -O2) menu function: 280 -> 60 with both
(each one neutral alone). Children: the collapsed branch, and the collapsed branch with the arms swapped under the negated
condition (a leading `!` is removed instead of doubled). Nothing is offered when the arms differ.
"""
import re

from .call_result_join_copy import ELSE, IF, _blocks, _skip, _statement_end
from .integer_repair_support import edit, view
from .call_carrier_pointer_split import UNORDERED
from .pattern_repairs import close

FAMILY = 'chained_identical_arm_flip'
COLLAPSE_FAMILY = 'chained_identical_arm_collapse'
FAMILIES = (COLLAPSE_FAMILY, FAMILY)


def _arm(clean, start, limit):
    """(text without its braces, end) of the statement at `start`."""
    end = _statement_end(clean, start, limit)
    if end is None:
        return None
    text = clean[start:end].strip()
    if text.startswith('{') and text.endswith('}'):
        text = text[1:-1]
    return text, end


def _negate(condition):
    condition = condition.strip()
    if condition.startswith('!') and not condition.startswith('!='):
        inner = condition[1:].strip()
        if inner.startswith('(') and close(inner, 0, '(', ')') == len(inner):
            return inner[1:-1].strip()
        if re.fullmatch(r'[\w.>\-\[\]]+', inner):
            return inner
    return f'!({condition})'


def _chain(clean, start, limit):
    """(condition, X, Y, end) of an `if (C) X else if (D) Y else Y` statement at `start`, with Y written the same twice."""
    hit = IF.match(clean, start)
    if not hit:
        return None
    after = close(clean, hit.end() - 1, '(', ')')
    cond = clean[hit.end():after - 1]
    first = _arm(clean, _skip(clean, after), limit)
    if not first:
        return None
    other = ELSE.match(clean, _skip(clean, first[1]))
    if not other:
        return None
    inner = _skip(clean, other.end())
    inner_hit = IF.match(clean, inner)
    if not inner_hit:
        return None
    inner_after = close(clean, inner_hit.end() - 1, '(', ')')
    second = _arm(clean, _skip(clean, inner_after), limit)
    if not second:
        return None
    other = ELSE.match(clean, _skip(clean, second[1]))
    if not other:
        return None
    third = _arm(clean, _skip(clean, other.end()), limit)
    if not third or re.sub(r'\s+', '', second[0]) != re.sub(r'\s+', '', third[0]):
        return None
    return cond, first[0], second[0], third[1]


def variants(source, name):
    part = view(source, name)
    if not part or UNORDERED.search(part.body):
        return []
    clean = part.clean
    body_end = clean.rfind('}', part.opening, part.end)
    out = []
    for spans in _blocks(clean, part.opening + 1, body_end):
        for first, _ in spans:
            found = _chain(clean, first, body_end)
            if not found:
                continue
            cond, x, y, end = found
            line = clean.rfind('\n', 0, first) + 1
            lead = clean[line:first] if not clean[line:first].strip() else ''
            plain = f'if ({cond})\n{lead}{{{x}}}\n{lead}else\n{lead}{{{y}}}'
            swapped = f'if ({_negate(cond)})\n{lead}{{{y}}}\n{lead}else\n{lead}{{{x}}}'
            out.append((COLLAPSE_FAMILY, edit(source, [(first, end, plain)])))
            out.append((FAMILY, edit(source, [(first, end, swapped)])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 50}  # the registry: no caller wiring (registry.py)
