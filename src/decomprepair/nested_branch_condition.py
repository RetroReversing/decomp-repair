"""An `if`/`else` whose two arms only test again and do the same thing, written as one conditional condition.

    if (v > 0.0f) {                     if ((v > 0.0f) ? (v < EPS) : (-v < EPS)) {
        if (v < EPS) {                      v = 0.0f;
            v = 0.0f;                   }
        }                  ->
    } else {
        if (-v < EPS) {                 if (((v > 0.0f) ? v : -v) < EPS) {      (the second child, for an absolute value)
            v = 0.0f;                       v = 0.0f;
        }                               }
    }

The nested form lets the compiler's cross-jumping merge the inner branch with the store, where the target keeps one
branch per arm and shares only the store. m2c writes the same code with one arm's test as a `goto` into the other's
(`if (!(v > 0.0f)) { if (-v < EPS) goto block_6; } else if (v < EPS) { block_6: v = 0.0f; }`), read too. The two sources
mean the same: the outer test runs once, then one inner test, then the statements.

Controlled on one 114-instruction N64 line-intersection routine with two such clamps (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O1`): 1780 -> 1300 with the other arms already as in the target, and two run-weight steps
from there reached 0. Labels `nested_branch_condition`.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT
from .pattern_repairs import close, negate

FAMILIES = ('nested_branch_condition',)


def _skip(clean, at):
    return re.compile(r'\s*').match(clean, at).end()


def _statement(source, clean, at):
    """(condition, body, label_goto, end) of the `if` at `at` with no `else`, its body a block or a lone `goto`."""
    head = re.compile(r'if\s*\(').match(clean, at)
    if not head:
        return None
    shut = close(clean, head.end() - 1)
    if not shut:
        return None
    condition = source[head.end():shut - 1].strip()
    start = _skip(clean, shut)
    if clean.startswith('{', start):
        end = close(clean, start, '{', '}')
        if not end:
            return None
        body = source[start + 1:end - 1]
    else:
        lone = re.compile(rf'goto\s+{IDENT}\s*;').match(clean, start)
        if not lone:
            return None
        end, body = lone.end(), lone[0]
    if re.compile(r'\s*else\b').match(clean, end):
        return None
    return condition, body, end


def _arm(source, clean, at):
    """The inner `if` of an arm that starts at `at`: a block holding only it, or the `if` itself (`else if`)."""
    if clean.startswith('{', at):
        end = close(clean, at, '{', '}')
        if not end:
            return None
        inner = _statement(source, clean, _skip(clean, at + 1))
        if not inner or _skip(clean, inner[2]) != end - 1:
            return None
        return inner[0], inner[1], end
    return _statement(source, clean, at)


def _merged(clean, first, second):
    """The statements both arms run: equal bodies, or one arm's `goto L;` into the other's `L: ...`."""
    squeeze = [' '.join(body.split()) for body in (first, second)]
    for jump, target, kept in ((squeeze[0], squeeze[1], second), (squeeze[1], squeeze[0], first)):
        hit = re.fullmatch(rf'goto ({IDENT}) ?;', jump)
        if not hit:
            continue
        label = hit[1]
        if (not re.match(rf'{label} ?:(?!:)', target)
                or len(re.findall(rf'\bgoto\s+{label}\s*;', clean)) != 1
                or re.search(rf'&&\s*{label}\b\s*[;,}})]', clean)):
            return None
        return re.sub(rf'(?<![\w.>]){label}\s*:[ \t]*(?:\n[ \t]*)?', '', kept, count=1)
    if squeeze[0] != squeeze[1] or not squeeze[0] or re.search(rf'(?:^|[;{{}}] ?){IDENT} ?:(?!:)', squeeze[0]):
        return None
    return first


def _positive(condition):
    """(`test`, swapped) with a whole-condition `!(...)` taken off, so the arms trade places."""
    if condition.startswith('!'):
        rest = condition[1:].strip()
        if rest.startswith('(') and close(rest, 0) == len(rest):
            return rest[1:-1].strip(), True
    return condition, False


def _bare(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _absolute(test, then, other):
    """`((v > 0) ? v : -v) < K` for the arms `v < K` and `-v < K` of the test `v > 0`."""
    sign = re.fullmatch(rf'({IDENT})\s*>=?\s*0(?:\.0*)?[fF]?', _bare(test))
    if not sign:
        sign = re.fullmatch(rf'0(?:\.0*)?[fF]?\s*<=?\s*({IDENT})', _bare(test))
    if not sign:
        return None
    value = sign[1]
    plain = re.fullmatch(rf'{value}\s*(<=?)\s*([\w.+-]+)', _bare(then))
    minus = re.fullmatch(rf'(?:-\s*{value}|\(\s*-\s*{value}\s*\))\s*(<=?)\s*([\w.+-]+)', _bare(other))
    if not plain or not minus or plain.groups() != minus.groups():
        return None
    return f'(({_bare(test)}) ? {value} : -{value}) {plain[1]} {plain[2]}'


def _sites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    sites, taken = [], span[0]
    for hit in re.finditer(r'\bif\s*\(', clean[:span[1]]):
        if hit.start() < taken:
            continue
        shut = close(clean, hit.end() - 1)
        start = _skip(clean, shut) if shut else 0
        if not shut or not clean.startswith('{', start):
            continue
        first = _arm(source, clean, start)
        if not first:
            continue
        other = re.compile(r'\s*else\b\s*').match(clean, first[2])
        second = _arm(source, clean, other.end()) if other else None
        if not second:
            continue
        body = _merged(clean, first[1], second[1])
        if body is None:
            continue
        test, swapped = _positive(source[hit.end():shut - 1].strip())
        then, otherwise = (second[0], first[0]) if swapped else (first[0], second[0])
        if re.search(r'[?:;{}]', _blank(test + then + otherwise)):
            continue
        line = source.rfind('\n', 0, hit.start()) + 1
        margin = re.match(r'[ \t]*', source[line:])[0]
        block = f'{{\n{margin}    {body.strip()}\n{margin}}}'
        ternary = f'if (({test}) ? ({then}) : ({otherwise})) {block}'
        value = _absolute(test, then, otherwise)
        if not value and (flipped := negate(test)):
            value = _absolute(flipped, otherwise, then)
        sites.append((hit.start(), second[2], ternary, f'if ({value}) {block}' if value else None))
        taken = second[2]
    return sites


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    sites = _sites(source, name)[:6]
    if not sites:
        return []
    children = [_apply(source, [(a, b, ternary) for a, b, ternary, _ in sites])]
    if any(absolute for *_, absolute in sites):
        children.append(_apply(source, [(a, b, absolute or ternary) for a, b, ternary, absolute in sites]))
    if len(sites) > 1:
        children += [_apply(source, [(a, b, ternary)]) for a, b, ternary, _ in sites]
    return [('nested_branch_condition', child) for child in dict.fromkeys(children)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
