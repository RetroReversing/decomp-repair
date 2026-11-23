"""A loop that tests a byte local reloaded from a member at its bottom: the member itself as the test.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 515: a row index was
walked while it stayed at or below the selected row, written `selected = w->selected; i = 0; while (i <= selected) {
...; ++i; selected = w->selected; }`, and the loop's exit arm lowered the member with a second local. With the byte local
as the loop's carried value the compiler masked it at every compare (`andi $v1,$v1,0xff`), kept the loop guard as a real
compare (`slti $v0,$v1,0`) and kept an 8-byte hole in the frame. The target has the byte straight from the load in
`$v1`, a guard that is a constant (`move $v0,$zero; bnez $v0`), the exit arm's `bltz` branching to the zero store placed
after the other arm, and no local at all: `while (i <= w->selected)` with the arms reading the member
(515 -> 230 in one step, 14 of the 17 differing rows).

member_test_loop
    `v = P->f; i = 0; while (i <= v) { body; ++i; v = P->f; }` becomes `i = 0; while (i <= P->f) { body; ++i; }` with
    the reads of `v` in the body reading `P->f`. Offered only when the body writes `P->f` only in blocks that end in
    `break;` (so every read of `v` still sees the member's value), `v` is not read after the loop and the reload is the
    loop's last statement.
member_test_loop_swap
    The same, and the body's `if (c) A else B` over a sign test (`x < 0`, `x >= 0`) written the other way round
    (`if (x >= 0) B else A`): the zero-store arm moves after the other one, the layout the target has. The two edits
    only pay off together.

Hypothesis from the match, not from the compiler source: the byte is known zero-extended only where cse sees the load
in the same block, and a local that is also assigned `i` (or copied) keeps a narrow register that must be masked.
The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'member_test_loop'
FAMILY_SWAP = 'member_test_loop_swap'
FAMILIES = (FAMILY, FAMILY_SWAP)
LIMIT = 4
_LOOP = re.compile(
    rf'(?P<init>(?P<v>{IDENT})\s*=\s*(?P<member>{IDENT}\s*->\s*{IDENT})\s*;)\s*'
    rf'(?P<counter>{IDENT})\s*=\s*0\s*;\s*(?P<wrap>\{{\s*)?while\s*\(\s*(?P=counter)\s*(?P<op><=|<)\s*(?P=v)\s*\)\s*\{{')
_SIGN = re.compile(rf'(?P<x>{IDENT})\s*(?P<op><|>=)\s*0')


def _names(text, name):
    return [m for m in re.finditer(rf'\b{re.escape(name)}\b', text) if not re.search(r'(?:->|\.)\s*$', text[:m.start()])]


def _enclosing_blocks(text, position):
    """The `{ }` spans around `position`, innermost first."""
    stack, spans = [], []
    for m in re.finditer(r'[{}]', text[:position]):
        if m[0] == '{':
            stack.append(m.start())
        elif stack:
            stack.pop()
    for start in reversed(stack):
        stop = close(text, start, '{', '}')
        if stop is not None:
            spans.append((start, stop))
    return spans


def _swap_arms(body, offset):
    """Edits that write one `if (x < 0) A else B` (or `x >= 0`) the other way round: (start, end, text) or None."""
    for head in re.finditer(r'\bif\s*\(', body):
        stop = close(body, head.end() - 1)
        if stop is None:
            continue
        sign = _SIGN.fullmatch(body[head.end():stop - 1].strip())
        if not sign:
            continue
        first = _arm(body, stop)
        if not first:
            continue
        other = re.compile(r'\s*else\b\s*').match(body, first[1])
        second = _arm(body, other.end()) if other else None
        if not second:
            continue
        flipped = '>=' if sign['op'] == '<' else '<'
        text = f'if ({sign["x"]} {flipped} 0) {body[second[0]:second[1]].strip()} else {body[first[0]:first[1]].strip()}'
        return offset + head.start(), offset + second[1], text
    return None


def _arm(body, at):
    """(start, end) of the statement at `at`: a braced block or one statement ending in `;`."""
    while body[at:at + 1].isspace():
        at += 1
    if body[at:at + 1] == '{':
        stop = close(body, at, '{', '}')
        return (at, stop) if stop else None
    found = re.compile(r'[^;{}]*;').match(body, at)
    return (at, found.end()) if found and not re.match(r'\s*(?:if|else)\b', body[at:]) else None


def _children(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    clean, result = part.clean, []
    for loop in _LOOP.finditer(clean, part.opening + 1, part.end):
        v, member = loop['v'], re.sub(r'\s+', '', loop['member'])
        open_at = loop.end() - 1
        stop = close(clean, open_at, '{', '}')
        if stop is None:
            continue
        body = clean[open_at + 1:stop - 1]
        tail = re.search(rf'\+\+\s*{re.escape(loop["counter"])}\s*;\s*{re.escape(v)}\s*=\s*{re.escape(loop["member"])}\s*;\s*$', body)
        tail = tail or re.search(rf'{re.escape(loop["counter"])}\s*\+\+\s*;\s*{re.escape(v)}\s*=\s*'
                                 rf'{re.escape(loop["member"])}\s*;\s*$', body)
        if not tail:
            continue
        inner = body[:tail.start()]
        if any(re.match(r'\s*(?:\+\+|--|[-+*/&|^]?=(?!=))', inner[m.end():]) for m in _names(inner, loop['counter'])):
            continue
        if any(re.match(r'\s*(?:\+\+|--|[-+*/&|^]?=(?!=))', inner[m.end():]) for m in _names(inner, v)):
            continue
        base = re.escape(member.split('->')[0]) + r'\s*->\s*' + re.escape(member.split('->')[1])
        stores = [m for m in re.finditer(rf'\b{base}\s*(?:[-+*/&|^]?=(?!=)|\+\+|--)', inner)]
        ends = [m for m in re.finditer(r'\bbreak\s*;', inner)]
        if any(not any(inner[a + 1:b - 1].rstrip().endswith('break;') for a, b in _enclosing_blocks(inner, s.start())) for s in stores):
            continue
        if stores and not ends:
            continue
        after = clean[stop:part.end]
        if any(not re.match(r'\s*=(?!=)', after[m.end():]) for m in _names(after, v)):
            continue
        base_at = open_at + 1
        new_inner = inner
        reads = _names(inner, v)
        for m in reversed(reads):
            new_inner = new_inner[:m.start()] + member.replace(' ', '') + new_inner[m.end():]
        member_text = member.replace(' ', '')
        counter = loop['counter']
        wrap = '{\n    ' if loop['wrap'] else ''
        head = f'{counter} = 0;\n    {wrap}while ({counter} {loop["op"]} {member_text}) {{'
        step = body[tail.start():tail.end()].split(';')[0].strip() + ';'
        removal = (loop.start(), loop.end(), head)
        tail_edit = (base_at, stop - 1, new_inner.rstrip() + f'\n    {step}\n')
        result.append((FAMILY, edit(source, [removal, tail_edit])))
        swap = _swap_arms(new_inner, base_at)
        if swap:
            start, end, text = swap
            relative = (start - base_at, end - base_at)
            swapped = new_inner[:relative[0]] + text + new_inner[relative[1]:]
            result.append((FAMILY_SWAP, edit(source, [removal, (base_at, stop - 1, swapped.rstrip() + f'\n    {step}\n')])))
    return result[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
