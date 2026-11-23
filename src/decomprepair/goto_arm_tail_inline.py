"""A `goto` to the tail of another switch arm, written as the statements it would run.

    case 2: ... else { goto block_75; } ... break;          default: ... else { block_75: done = 0; } break;

m2c joins the arms of a state machine that finish the same way with `goto`: the labelled statements sit in one arm's last
block and the other arms jump into it. Where nothing follows the label's block but the arm's `break;` (the `else` arms
the label skips are not run either), and nothing follows the `goto`'s block but the arm's `break;`, the jump is the same
program as the statements written where it is: the game's arms each finished by themselves, and the compiler's
cross-jumping merged the identical tails again. The jump table's arms differ otherwise: the label's arm owns
a pseudo-register web that the `goto` makes live across the whole switch (the continue flag of a 417-instruction input
handler had 14 references and ranked below its three masks; the target's order was the other one).

Offered once for the function (every such `goto` in one child, and the labels it leaves unused removed): a label whose
statements run to the end of their block, with the block followed only by skipped `else` arms and `break;`, and `goto`s
whose block is followed only by closing braces, skipped `else` arms and `break;`. Labels with labels or `goto`s of their
own inside are left alone. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'goto_arm_tail_inline'
FAMILIES = (FAMILY,)
_LABEL = re.compile(rf'(?m)(?:^|(?<=[;{{}}]))\s*(?P<l>{IDENT})\s*:(?!:)')
_GOTO = re.compile(rf'\bgoto\s+(?P<l>{IDENT})\s*;')


def _end_of_block(clean, at, limit):
    depth = 0
    for pos in range(at, limit):
        if clean[pos] == '{':
            depth += 1
        elif clean[pos] == '}':
            if depth == 0:
                return pos
            depth -= 1
    return None


def _only_exit_follows(clean, at, limit):
    """Whether, from `at`, nothing but closing braces, `else` arms that are skipped and `break;` follow."""
    while at < limit:
        rest = re.compile(r'\s*').match(clean, at).end()
        if clean.startswith('}', rest):
            at = rest + 1
        elif re.compile(r'else\b').match(clean, rest):
            after = rest + 4
            pre = re.compile(r'\s*if\s*\(').match(clean, after)
            if pre:
                after = close(clean, pre.end() - 1)
            block = re.compile(r'\s*\{').match(clean, after)
            if not block or not after:
                return False
            at = close(clean, block.end() - 1, '{', '}')
            if not at:
                return False
        else:
            return bool(re.compile(r'break\s*;').match(clean, rest))
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    edits = []
    gone = {}
    inlined = {}
    for label in _LABEL.finditer(clean, part.opening + 1, part.end):
        text = label['l']
        if text in ('default', 'case') or not re.search(rf'\bgoto\s+{text}\s*;', clean[part.opening:part.end]):
            continue
        end = _end_of_block(clean, label.end(), part.end)
        if end is None:
            continue
        statements = source[label.end():end].strip()
        if not statements or re.search(rf'\bgoto\b|^\s*{IDENT}\s*:(?!:)', clean[label.end():end], re.M) or '{' in statements:
            continue
        if not _only_exit_follows(clean, end + 1, part.end):
            continue
        inlined[text] = (label, statements)
    for hit in _GOTO.finditer(clean, part.opening + 1, part.end):
        if hit['l'] not in inlined:
            continue
        label, statements = inlined[hit['l']]
        if hit.start() > label.start() and hit.start() < _end_of_block(clean, label.end(), part.end):
            continue
        end = _end_of_block(clean, hit.end(), part.end)
        if end is None or not _only_exit_follows(clean, end, part.end):
            continue
        edits.append((hit.start(), hit.end(), statements))
        gone[hit['l']] = gone.get(hit['l'], 0) + 1
    if not edits:
        return []
    for text, count in gone.items():
        if len(re.findall(rf'\bgoto\s+{text}\s*;', clean[part.opening:part.end])) == count:
            label = inlined[text][0]
            edits.append((label.start(), label.end(), ' '))
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
