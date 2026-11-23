"""A float assigned from one binary operation, written as an assignment and a compound assignment.

`v = (-x) * rate;` against `v = -x; v *= rate;`. On KMC GCC 2.7.2 (N64) the first form expands to a temporary for
the negation and a product that ties to the variable only afterwards; the second writes the negation straight into the
variable's pseudo, so the pseudo is live through the multiply and takes the lower-numbered register while the other
pseudos of the function (a constant loaded after the negation, here a `-0.05f` that a join shares with another arm)
move to the one that was free. One steer function (a 147-instruction camera follower; its first arm already wrote
`dx *= rate` and its last `dx = (-x) * rate`) sat at 70 with fourteen register rows and nothing else; this one edit
took it to 0. The rows were all registers in one float chain: a statement-level, one-line spelling no earlier family
offered. Hypothesis (not confirmed in the compiler's source): local-alloc's quantity ordering and `combine`'s fold
of the temporary decide it; the measured fact is the 70 -> 0.

Children, for a float local (or parameter) assigned from exactly one binary `*`, `/`, `+` or `-` of two operands that
do not mention it and call nothing: each such statement split on its own (`+` and `*` also with the operands swapped,
since the target may have written either), and every statement of the function split together as one child, as the
edits of a late match often only pay off combined. A statement under an unbraced `if` is left alone. Only MIPS, and a
function with no `volatile`. The candidate is never a verdict: the judge decides.

An operand may read a field through `->` (`v = ((T *) p)->f / k;` as `v = ((T *) p)->f; v /= k;`, the load then goes
straight into `v`'s register: 85 -> 75 on a 1300-instruction KMC GCC 2.7.2 controller routine), and statements that
load come first, before the cap.
"""
import re

from .csource import _blank, find

FAMILY = 'compound_operand_split'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_TYPE = re.compile(r'\b(?:f32|float|f64|double)\b([^;(){}]*);')
_STATEMENT = re.compile(rf'(?<=[;{{}}])(\s*)({_ID})\s*=\s*([^;{{}}=]+);')
_OPERAND_END = re.compile(r'[\w)\]]')
_LIMIT = 24


def _float_names(text):
    """Names declared as float scalars in `text` (a declarator list, an initializer or a pointer is accounted for)."""
    out = set()
    for hit in _TYPE.finditer(text):
        for part in hit[1].split(','):
            name = part.split('=')[0].strip()
            if re.fullmatch(_ID, name):
                out.add(name)
    return out


def _split(rhs):
    """(left, op, right) of an expression with exactly one binary operator at depth 0, else None."""
    depth, found, prev = 0, [], ''
    for i, c in enumerate(rhs):
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0 and not c.isspace():
            nxt = rhs[i + 1:i + 2]
            if c in '*/+-' and nxt in '=+-' and c in '+-' and nxt == c:
                return None
            if c == '-' and nxt == '>':  # a member access (`p->f`): part of the operand
                prev = c
                continue
            if c in '*/+-':
                if nxt == '=':
                    return None
                exponent = c in '+-' and prev in 'eE' and re.search(r'\d[eE]$', rhs[:i])
                if prev and _OPERAND_END.match(prev) and not exponent:
                    found.append(i)
            elif not (c.isalnum() or c in '_.' or (c == '>' and prev == '-')):
                return None
        if not c.isspace():
            prev = c
    if depth != 0 or len(found) != 1:
        return None
    return rhs[:found[0]].strip(), rhs[found[0]], rhs[found[0] + 1:].strip()


def _paren(text):
    return text if re.fullmatch(r'-?[\w.]+', text) else f'({text})'


def _simple(operand, name):
    return (operand and not re.search(rf'\b{name}\b', operand) and not re.search(rf'{_ID}\s*\(', operand)
            and not re.search(r'[=<!&|?]|(?<!-)>|\+\+|--', operand))


def _children(clean, lo, hi, floats):
    """[(start, end, [replacement, ...])] for each statement that can be split."""
    out = []
    for hit in _STATEMENT.finditer(clean, lo, hi):
        name = hit[2]
        if name not in floats:
            continue
        parts = _split(hit[3].strip())
        if not parts:
            continue
        left, op, right = parts
        left = re.sub(r'^\(\s*(-?\s*[\w.]+)\s*\)$', r'\1', left)
        if not _simple(left, name) or not _simple(right, name):
            continue
        indent = hit[1].split('\n')[-1]
        forms = [(left, right)] + ([(right, left)] if op in '+*' else [])
        out.append((hit.start(2), hit.end(), [f'{name} = {a};\n{indent}{name} {op}= {_paren(b)};' for a, b in forms]))
    # a load split from its operation first (the target's load straight into the local), then the rest in order:
    # a 1300-instruction function had its one such statement past the first _LIMIT
    out.sort(key=lambda item: not re.search(r'->|\[|\*\s*\(', item[2][0].split(';')[0]))
    return out[:_LIMIT]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return []
    floats = _float_names(clean[span[0]:span[1]])
    found = _children(clean, opening, span[1], floats)
    out = []
    for start, end, forms in found:
        for text in forms:
            out.append((FAMILY, source[:start] + text + source[end:]))
    if len(found) > 1:
        src = source
        for start, end, forms in reversed(found):
            src = src[:start] + forms[0] + src[end:]
        out.append((FAMILY, src))
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
