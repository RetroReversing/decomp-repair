"""A counter incremented inside the `if` that tests it, and the increment written after the `if` instead.

`if ((temp++) != index) { ... }` makes gcc copy the old value for the compare (`move $v0, $a1; beq $v0, $a0, ...;
addiu $a1, $a1, 1`: the copy and the new value are live together, so they cannot share a register). In KMC GCC 2.7.2
(`-G0 -mips3 -mgp32 -mfp32 -O2`) the target tested the counter itself and incremented it in the branch's delay slot
(`beq $a1, $a0, L; addiu $a1, $a1, 1`): the increment comes *after* the test in the insn stream, and reorg moves it into
the slot because the guarded body never reads the counter. Written as `if (temp != index) { ... } temp++;` the compare
reads the counter, there is no copy, and the loop of a 154-instruction function lost one instruction and two registers
(320 -> 215 of the final 0 in docs/learnings/function/narrow-copy-web-save-slot-rank.md).

`postincrement_after_test` rewrites `if (X++ <op> Y)` / `if (Y <op> X++)` / `if ((X++) ...)` (X a plain local) to the
plain test with `X++;` after the whole `if` statement. The program is the same only when neither arm of the `if` reads or
writes `X` and neither leaves the block early, so those are the only places it applies: no `X` in the arms, no
`break`/`continue`/`goto`/`return`/`case` in them, and `X` not read by the rest of the condition.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'postincrement_after_test'
FAMILIES = (FAMILY,)
LEAVES = re.compile(r'\b(?:break|continue|goto|return|case|default)\b|\b' + IDENT + r'\s*:(?!:)')


def _statement_end(clean, at, limit):
    """The end of the statement that starts at `at` (a braced block, or up to its `;`), or None."""
    while at < limit and clean[at].isspace():
        at += 1
    if at >= limit:
        return None
    if clean[at] == '{':
        return close(clean, at, '{', '}')
    stop = clean.find(';', at, limit)
    return stop + 1 if stop >= 0 else None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean, limit = part.clean, part.end - 1
    result = []
    for statement in re.finditer(r'\bif\s*\(', clean[part.opening + 1:limit]):
        start = part.opening + 1 + statement.start()
        previous = clean[:start].rstrip()
        if not previous or previous[-1] not in ';{}':
            continue  # `else if`, a loop's body or a label: the increment would run on other paths
        opening = part.opening + 1 + statement.end() - 1
        closing = close(clean, opening)
        if closing is None:
            continue
        condition = clean[opening + 1:closing - 1]
        test = re.fullmatch(rf'\s*\(?\s*({IDENT})\s*\+\+\s*\)?\s*(==|!=|<=|>=|<|>)\s*(.+?)\s*', condition, re.S)
        mirrored = re.fullmatch(rf'\s*(.+?)\s*(==|!=|<=|>=|<|>)\s*\(?\s*({IDENT})\s*\+\+\s*\)?\s*', condition, re.S)
        if test:
            counter, other = test[1], test[3]
        elif mirrored:
            counter, other = mirrored[3], mirrored[1]
        else:
            continue
        if (re.search(rf'(?<![\w.>]){re.escape(counter)}\b', other) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', other)
                or _address_taken(part.body, counter)):
            continue
        end = _statement_end(clean, closing, limit)
        if end is None:
            continue
        arms = clean[closing:end]
        after = re.match(r'\s*else\b', clean[end:limit])
        if after:
            end = _statement_end(clean, end + after.end(), limit)
            if end is None:
                continue
            arms = clean[closing:end]
        if re.search(rf'(?<![\w.>]){re.escape(counter)}\b', arms) or LEAVES.search(arms):
            continue
        plain = (f'{counter} {test[2]} {other}' if test else f'{other} {mirrored[2]} {counter}')
        edits = [(opening + 1, closing - 1, plain), (end, end, f'\n{" " * _indent(clean, start)}{counter}++;')]
        result.append((FAMILY, edit(source, edits)))
    return result


def _indent(clean, at):
    line = clean.rfind('\n', 0, at) + 1
    return len(clean[line:at]) - len(clean[line:at].lstrip())


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
