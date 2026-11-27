"""A condition's loaded value repeated in an arm, held in a local set before the `if`.

`if (r.alpha + 8 >= 0xFF) { r.alpha = 0xFF; } else { r.alpha = r.alpha + 8; }` computes the sum twice. Under `-O1`
(KMC GCC 2.7.2, N64) nothing merges the two across the branch, and under other levels the sum lands in `$v0` where the
target keeps it in its own register (`lbu $a1; addiu $a1, $a1, 8; sltiu $v0, $a1, 0xff` and `sb $a1` in the other arm).
The source computed it once: `{ u32 t = r.alpha + 8; if (t >= 0xFF) { r.alpha = 0xFF; } else { r.alpha = t; } }`
(665 -> 0 on a 232-instruction fade state machine, where the library's other children stopped at 665). The compared
value can be signed or unsigned, so both locals are offered.

A proposal needs: a comparison `E OP K` against a literal, E a read of memory with no call, assignment or increment,
and an arm whose first statement is `L = E;`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'condition_value_local'
FAMILIES = (FAMILY,)
LIMIT = 8

_EFFECT = re.compile(r'\+\+|--|(?<![=!<>])=(?!=)|(?<![\w.>])(?!sizeof\b)[A-Za-z_]\w*\s*\(')
_LITERAL = re.compile(r'\s*-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*')
_COMPARE = re.compile(r'(?<![<>=!-])(?:<=|>=|==|!=|<(?!<)|>(?!>))')


def _strip(text):
    """`text` without outer whitespace and the parentheses around all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _comparison(condition):
    """(left, operator, literal) for a condition that is one comparison against a literal, else None."""
    condition = _strip(condition)
    depth, level = 0, []
    for ch in condition:
        depth += ch in '(['
        depth -= ch in ')]'
        level.append(depth)
    cuts = [m for m in _COMPARE.finditer(condition) if level[m.start()] == 0]
    if len(cuts) != 1 or '&&' in condition or '||' in condition or '?' in condition:
        return None
    right = condition[cuts[0].end():]
    if not _LITERAL.fullmatch(right):
        return None
    return condition[:cuts[0].start()].strip(), cuts[0][0], right.strip()


def _key(text):
    return re.sub(r'\s+', '', _strip(text))


def variants(source, name):
    """Proposals: the compared value in a local, read by the condition and by the arm that stores it."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    if re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    fresh = 'compared'
    while re.search(rf'\b{fresh}\b', clean):
        fresh += '_'
    out = []
    for guard in re.finditer(r'\bif\s*\(', clean[span[0]:span[1]]):
        at = span[0] + guard.start()
        paren = span[0] + guard.end() - 1
        paren_end = close(clean, paren, '(', ')')
        parts = _comparison(source[paren + 1:paren_end - 1]) if paren_end else None
        if not parts:
            continue
        left, operator, literal = parts
        value = _strip(left)
        if _EFFECT.search(value) or not re.search(r'->|\[|\.\s*[A-Za-z_]|(?:^|[(+\-&|^])\s*\*', value):
            continue
        arms, pos = [], paren_end
        brace = re.compile(r'\s*\{').match(clean, pos)
        if not brace:
            continue
        end = close(clean, brace.end() - 1, '{', '}')
        if not end:
            continue
        arms.append((brace.end(), end - 1))
        other = re.compile(r'\s*else\s*\{').match(clean, end)
        if other:
            other_end = close(clean, other.end() - 1, '{', '}')
            if not other_end:
                continue
            arms.append((other.end(), other_end - 1))
            end = other_end
        elif re.compile(r'\s*else\b').match(clean, end):
            continue
        for start, stop in arms:
            first = re.compile(r'\s*([^;{}]+?)\s*(?<![=!<>+\-*/&|^])=(?!=)\s*([^;{}]+);').match(clean, start, stop)
            if not first or _key(source[first.start(2):first.end(2)]) != _key(value):
                continue
            if _EFFECT.search(first[1]) or re.match(r'(?:if|while|for|return|switch)\b', first[1]):
                continue
            for kind in ('u32', 's32'):
                body = (source[at:paren + 1] + f'{fresh} {operator} {literal}' + source[paren_end - 1:first.start(2)]
                        + fresh + source[first.end(2):end])
                out.append((FAMILY, source[:at] + f'{{ {kind} {fresh} = {value}; {body} }}' + source[end:]))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
