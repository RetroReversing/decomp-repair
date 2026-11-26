"""A comparison of two loads written with its sides the other way round.

gcc loads a comparison's left operand first, so `a < b` and `b > a` differ in which register each load takes (and,
for floats, which way `c.lt.s` reads). m2c writes the order its reading of the branch gave: two N64 functions, a
float and a byte comparison of two fields, were exact with the sides swapped (`f(a) < f(b)` as `f(b) > f(a)`). The
meaning is the same; only the operand order changes.

The `((Field_f32 *) (((char *) base) + 0x14))->v` cells that m2c's drafts for this project use are operands too: on a
1137-instruction player-update routine (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) `!(field < locals.vec58[1])`
written `!(locals.vec58[1] > field)` loaded the two floats in the target's order (570 -> 550 and a row less).

Every comparison is offered (a cap of four once left the later ones unreachable), and a comparison repeated with only
its numbers changed (unrolled vector components, `a[0] < b[0]`, `a[1] < b[1]`, ...) also gets one child that swaps
all of its copies: a 144-instruction three-component bounds update (`-O1`) needed nine swaps, 90 -> 0 in three.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'comparison_sides'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
FIELD_TYPE = r'Field_[A-Za-z_]\w*'
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
LIMIT = 32  # single swaps offered


def _operand_end(text, start):
    """End of a load operand at `start`: `M2C_FIELD(...)`, `*(...)`, a name with `->`/`.`/`[...]`; or None."""
    m = re.match(r'\s*(M2C_FIELD\s*\(|\*\s*\()', text[start:])
    if m:
        paren = start + m.end() - 1
        return close(text, paren)
    m = re.match(r'\s*\(\s*\(\s*' + FIELD_TYPE + r'\s*\*\s*\)', text[start:])
    if m:  # `((Field_s16 *) (((char *) base) + 0x7A))->v`, the cell the project's drafts write
        stop = close(text, start + m.start() + text[start:].index('('))
        tail = re.match(r'\s*->\s*' + IDENT, text[stop:]) if stop else None
        return stop + tail.end() if tail else None
    m = re.match(r'\s*' + IDENT + r'(?:\s*(?:->|\.)\s*' + IDENT + r'|\s*\[[^\]]*\])+', text[start:])
    return start + m.end() if m else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    swaps = []  # (start, end, replacement, shape)
    for op in re.finditer(r'(?<![<>=!-])(<=|>=|<|>)(?![<>=])', clean[opening:end]):
        at = opening + op.start()
        # the left operand: the load ending right before the operator
        left_end = len(clean[:at].rstrip())
        left_start = None
        for cand in re.finditer(r'M2C_FIELD\s*\(|\*\s*\(|\(\s*\(\s*' + FIELD_TYPE + r'\s*\*\s*\)|' + IDENT, clean[max(opening, at - 400):left_end]):
            s = max(opening, at - 400) + cand.start()
            e = _operand_end(clean, s)
            if e == left_end and (s == 0 or not re.match(r'[\w.>]', clean[s - 1])):
                left_start = s
                break
        if left_start is None:
            continue
        right_start = opening + op.end()
        right_end = _operand_end(clean, right_start)
        if right_end is None or re.match(r'\s*[-+*/&|^]', clean[right_end:]) or re.search(r'[-+*/&|^]\s*$', clean[:left_start]):
            continue
        left = source[left_start:left_end].strip()
        right = source[right_start:right_end].strip()
        shape = tuple(re.sub(r'\d+', 'N', part) for part in (left, op[1], right))
        swaps.append((left_start, right_end, right + ' ' + FLIP[op[1]] + ' ' + left, shape))
    groups = {}
    for swap in swaps:
        groups.setdefault(swap[3], []).append(swap)
    # the repeated comparisons first: one child for all the copies, then each comparison alone
    chosen = [group for group in groups.values() if len(group) > 1] + [[swap] for swap in swaps[:LIMIT]]
    result, seen = [], set()
    for group in chosen:
        text = source
        for start, stop, replacement, _ in reversed(group):
            text = text[:start] + replacement + text[stop:]
        if text not in seen:
            seen.add(text)
            result.append((FAMILY, text))
    return result
