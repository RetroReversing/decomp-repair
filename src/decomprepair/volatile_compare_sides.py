"""A comparison of a plain value and a volatile read, with the read on the left: the volatile load comes first.

gcc expands a comparison's left operand first, and the scheduler keeps a volatile load where it was expanded (nothing
is moved across it), so `(s16) i < *(volatile s32 *) &bound` loads `i`'s extension (`sll`, `sra`) and then the bound, and
`*(volatile s32 *) &bound > (s16) i`, the same test, loads the bound first and extends `i` after it. m2c writes the
sides in the order its reading of the branch gave (`i < bound`); the original loop condition had the reload first
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, a save-slot loop whose `lw $v1, ($a3)` sat between the step's `move` and
the `sll`/`sra` of the counter: the last row of 60 -> 0 after `skip_join_loop_wrapper`). `comparison_sides` swaps two
plain loads (`M2C_FIELD`, `*(...)`, members); a volatile read through an inline helper (`rd((volatile s32 *) &g)`) or a
cast (`*(volatile s32 *) &g`) was no load to it, so the loop bound's order was never offered.

Offered: each relational operator with a side-effect-free left operand and a right operand that reads through a
`volatile` pointer, sides exchanged and the operator mirrored (`a < v` -> `v > a`). One child per operator. A candidate for
the exact judge, never a verdict."""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'volatile_compare_sides'
FAMILIES = (FAMILY,)
LIMIT = 6
FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}
OPERATOR = re.compile(r'(?<![<>=!\-])(<=|>=|<|>)(?![<>=])')
CALL = re.compile(r'[A-Za-z_]\w*\s*\(')
EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)')


def _left(clean, at, lo):
    depth = 0
    for j in range(at - 1, lo - 1, -1):
        ch = clean[j]
        if ch == ')':
            depth += 1
        elif ch == '(':
            if depth == 0:
                return j + 1
            depth -= 1
        elif depth == 0 and (ch in ',;{}?:' or clean[j - 1:j + 1] in ('&&', '||')
                             or (ch == '=' and clean[j - 1] not in '=!<>' and clean[j + 1] != '=')):
            return j + 1
    return lo


def _right(clean, at, hi):
    depth = 0
    for j in range(at, hi):
        ch = clean[j]
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                return j
            depth -= 1
        elif depth == 0 and (ch in ',;{}?:' or clean[j:j + 2] in ('&&', '||')
                             or (ch == '=' and clean[j + 1:j + 2] != '=' and clean[j - 1] not in '=!<>')):
            return j
    return hi


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for op in OPERATOR.finditer(clean, opening, end):
        left_start, right_end = _left(clean, op.start(), opening + 1), _right(clean, op.end(), end)
        left, right = clean[left_start:op.start()], clean[op.end():right_end]
        if (not left.strip() or not right.strip() or 'volatile' in left or 'volatile' not in right
                or CALL.search(left) or EFFECT.search(left) or EFFECT.search(right)
                or re.search(r'[<>]', re.sub(r'->|<<|>>', '', right)) or re.search(r'[<>]', re.sub(r'->|<<|>>', '', left))):
            continue
        text = edit(source, [(left_start, right_end,
                              f'{source[op.end():right_end].strip()} {FLIP[op[1]]} {source[left_start:op.start()].strip()}')])
        if text != source and text not in [t for _, t in out]:
            out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
