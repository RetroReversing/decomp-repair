"""A comparison that is one side of a bitwise `|`, stored in a local where it stands: `a | (n >= 7)` written
`a | (flag = (n >= 7))`.

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O1`), a 148-instruction N64 spawn routine: the target tests
`if (... && ((((flags >> 3) & 1) | (count >= 7U)) == 0))` with every value computed, `andi; sltiu $v1, 7; xori $v1, 1;
or $v0, $v0, $v1; bnez`. The unnamed comparison came out as two branches (`sltiu; beqz` then `bnez`), whatever its
spelling (`count > 6`, `!(count < 7)`, `(count < 7) ^ 1`, `!(... | ...)`); assigned to a local inside the expression
it stays a value. Measured on two sources of that function: 1065 -> 650 and 655 -> 240. That the folder turns an `|`
of unnamed truth values into jumps is a hypothesis; the compiler source was not read.

Offered for each parenthesised comparison next to a single `|` inside an `if` or `while` condition, one at a time and
then all together.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'or_compare_materialized'
FAMILIES = (FAMILY,)
LIMIT = 6

_COMPARE = re.compile(r'(?<![<>\-])(?:<=|>=|==|!=|<(?!<)|>(?!>))')


def _depth_zero(text):
    """`text` with everything inside brackets blanked."""
    out, depth = [], 0
    for char in text:
        if char in ')]':
            depth -= 1
        out.append(char if depth <= 0 else ' ')
        if char in '([':
            depth += 1
    return ''.join(out)


def _is_comparison(inner):
    top = _depth_zero(inner)
    if re.search(r'&&|\|\||[?,]|(?<![<>=!])=(?!=)', top):
        return False
    return len(_COMPARE.findall(top)) == 1 and not re.search(r'(?<!\|)\|(?!\|)|\^', top)


def _beside_or(clean, start, end):
    before = clean[:start].rstrip()
    after = clean[end:].lstrip()
    return (before.endswith('|') and not before.endswith('||')) or (
        after.startswith('|') and after[1:2] not in ('|', '='))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = []
    for condition in re.finditer(r'\b(?:if|while)\s*\(', clean[opening:end]):
        first = opening + condition.end() - 1
        last = close(clean, first)
        if not last:
            continue
        for at in range(first + 1, last - 1):
            if clean[at] != '(':
                continue
            stop = close(clean, at)
            if stop and _is_comparison(clean[at + 1:stop - 1]) and _beside_or(clean, at, stop) and (at, stop) not in sites:
                sites.append((at, stop))
    if not sites:
        return []
    names, n = [], 1
    while len(names) < len(sites):
        candidate = 'truth' if n == 1 else f'truth{n}'
        n += 1
        if not re.search(r'\b' + candidate + r'\b', clean):
            names.append(candidate)

    def build(chosen):
        text = source
        for index in sorted(chosen, reverse=True):
            at, stop = sites[index]
            text = text[:at] + f'({names[index]} = {source[at:stop]})' + text[stop:]
        declarations = ''.join(f'\n    int {names[index]};' for index in chosen)
        return text[:opening + 1] + declarations + text[opening + 1:]

    choices = [(i,) for i in range(len(sites))]
    if len(sites) > 1:
        choices.append(tuple(range(len(sites))))
    return [(FAMILY, build(chosen)) for chosen in choices[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
