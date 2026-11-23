"""A variable set to a constant and overwritten under a test, written with the constant as the arm of the negated test.

    n = 4;  if (flag != 0) { n = D_801002BA; }          if (flag != 0) { n = D_801002BA; } else { n = 4; }
                              ->      if (flag == 0) { n = 4; } else { n = D_801002BA; }

jump.c turns `if (c) x = a; else x = b;` into `x = b; if (c) x = a;` whenever `b` is a register or a constant (the
`Simplify if (...) x = a; else x = b;` rule), so the first two spellings and the one the game used all compile to the
constant set first, a single conditional load after it. The constant first in the *then* arm, the loaded value in the
else arm, is left alone by that rule: the constant's store sits in the delay slot of the branch and the spilled
variable's store (it lives across every call of the loop) is written once after the join instead of once per arm. A
417-instruction input handler needed exactly this for its loop count (`n = 4; if (flag) n = u16 global;`, spilled to the
stack): the `sh` after the join and the `li` in the branch's delay slot were the last rows, 770 -> 0, and the 4-byte
shift of everything after them (every branch and jump-table row) went with them.

Offered for `V = K;` followed by `if (C) { V = E; }` (braces or not), and for `if (C) { V = E; } else { V = K; }`, where
`K` is a numeric literal, `E` is not, and `C` is a single comparison or a name. A candidate rewrite; the exact judge
decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close, negate

FAMILY = 'const_arm_conditional_set'
FAMILIES = (FAMILY,)
_IF = re.compile(r'\bif\s*\(')


def _negated(cond):
    cond = cond.strip()
    flipped = negate(cond)
    if flipped:
        return flipped
    if re.fullmatch(rf'!\s*\(?{IDENT}\)?', cond):
        return cond.lstrip('!').strip().strip('()')
    return f'!({cond})' if re.fullmatch(rf'{IDENT}|\({IDENT}\)', cond) else None


def _arm(clean, at):
    """(start, end, statement) of a braced or braceless arm that is one assignment, from `at`; else None."""
    block = re.match(r'\s*\{\s*(?P<s>' + IDENT + r'\s*=\s*[^;{}]+;)\s*\}', clean[at:])
    if block:
        return at + block.start(), at + block.end(), block['s']
    bare = re.match(r'\s*(?P<s>' + IDENT + r'\s*=\s*[^;{}]+;)', clean[at:])
    return (at + bare.start(), at + bare.end(), bare['s']) if bare else None


def _assignment(statement):
    hit = re.fullmatch(rf'(?P<v>{IDENT})\s*=\s*(?P<e>[^;]+);', statement)
    return (hit['v'], hit['e'].strip()) if hit else (None, None)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if not shut:
            continue
        cond = clean[hit.end():shut - 1]
        flipped = _negated(cond)
        then = _arm(clean, shut)
        if not flipped or not then:
            continue
        v, expr = _assignment(then[2])
        otherwise = re.match(r'\s*else\b', clean[then[1]:])
        if otherwise:
            # if (C) { V = E; } else { V = K; }
            arm = _arm(clean, then[1] + otherwise.end())
            if not arm:
                continue
            v2, const = _assignment(arm[2])
            if v2 != v or not re.fullmatch(NUMBER, const or '') or re.fullmatch(NUMBER, expr or ''):
                continue
            text = f'if ({flipped}) {{ {v} = {const}; }} else {{ {v} = {expr}; }}'
            out.append((FAMILY, edit(source, [(hit.start(), arm[1], text)])))
            continue
        # V = K;  if (C) { V = E; }
        before = clean[:hit.start()].rstrip()
        prev = re.search(rf'(?P<s>(?P<v>{IDENT})\s*=\s*(?P<k>{NUMBER})\s*;)\Z', before)
        if not prev or prev['v'] != v or re.fullmatch(NUMBER, expr or ''):
            continue
        if before[:prev.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        text = f'if ({flipped}) {{ {v} = {prev["k"]}; }} else {{ {v} = {expr}; }}'
        out.append((FAMILY, edit(source, [(prev.start(), then[1], text)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
