"""A constant flag set by a redundant if/else chain, moved to the top of its block (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`).

`if (c) v = K; else if (!c) v = K; else v = J;` always leaves `K` in `v`, and a later `if (!v) goto L;` on it is the
never-taken branch some games' compiled code keeps (`li $t0,1; beqz $t0,L`, the flag in a temporary register and the
branch not folded because cse cannot see one constant through the chain). Where the chain sits decides the register:
written just before the test the flag lives a few instructions and takes `$v0`, `$v1` or an argument register (so a
store before it cannot move into the branch's delay slot: the flag's register is the stored value's); written at the
top of the block, ahead of the first `if` (and so of the block's call), the flag is live across that call, global.c has
no call-saved register left in a function that uses all nine, reload spills it, and `reload_cse_regs` turns the reload
back into the `li` before the branch, in `$t0`, with no stack traffic (hypothesis, from the register tables and the
dumps; the spill is not isolated further). On a 214-instruction slot-update loop the move alone took 70 -> 0
(docs/learnings/function/narrow-param-unwrap-bool-pair.md, a rewrite found after `narrow_bool_shapes`).

The move is exact: the chain's value does not depend on `c`, and nothing between its new place and its old one may
mention `v`.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'constant_flag_hoist'
FAMILIES = (FAMILY,)
CHAIN = re.compile(rf'if\s*\(\s*(?P<c>{IDENT})\s*\)\s*{{?\s*(?P<v>{IDENT})\s*=\s*(?P<k>{NUMBER})\s*;\s*}}?\s*'
                   rf'else\s+if\s*\(\s*!\s*(?P=c)\s*\)\s*{{?\s*(?P=v)\s*=\s*(?P=k)\s*;\s*}}?\s*'
                   rf'else\s*{{?\s*(?P=v)\s*=\s*{NUMBER}\s*;\s*}}?')


def _block_start(clean, at, opening):
    """The index just after the `{` of the block that holds `at` directly, or None."""
    depth = 0
    for index in range(at - 1, opening, -1):
        char = clean[index]
        if char == '}':
            depth += 1
        elif char == '{':
            if depth == 0:
                return index + 1
            depth -= 1
    return None


def _first_statement_with_if(clean, start, stop):
    """The start of the first `if (` statement at the block's own level between `start` and `stop`, or None."""
    depth = 0
    for index in range(start, stop):
        char = clean[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 0 and re.match(r'if\s*\(', clean[index:index + 8]) and not re.match(r'[\w.>]', clean[index - 1:index] or ' '):
            return index
    return None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean, out = part.clean, []
    for found in CHAIN.finditer(clean, part.opening, part.end):
        flag = found['v']
        start = _block_start(clean, found.start(), part.opening)
        if start is None:
            continue
        target = _first_statement_with_if(clean, start, found.start())
        if target is None or target >= found.start():
            continue
        between = clean[target:found.start()]
        if re.search(rf'(?<![\w.>]){re.escape(flag)}\b', between):
            continue
        line = source.rfind('\n', 0, target) + 1
        indent = re.match(r'[ \t]*', source[line:]).group()
        chain = source[found.start():found.end()].strip()
        stop = found.start() + len(source[found.start():found.end()].rstrip())
        first = source.rfind('\n', 0, found.start()) + 1
        begin = first if not source[first:found.start()].strip() else found.start()
        tail = re.match(r'[ \t]*\n', source[stop:])
        edits = [(begin, stop + (tail.end() if tail and begin == first else 0), ''), (line, line, f'{indent}{chain}\n')]
        text = edit(source, edits)
        if text != source:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}
