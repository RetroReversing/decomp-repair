"""`(A > B) ? B : A` written the way gcc 2.7.2's fold recognises as a minimum or maximum.

fold-const.c turns a conditional into MIN_EXPR/MAX_EXPR only when it reads `A op B ? A : B` (the arm that is
the comparison's left operand first) or, with constants, `A op C1 ? A : C2` with C1 and C2 one apart. The other
orientation, `A > B ? B : A`, stays a COND_EXPR, and fold then distributes any operator applied to it over both arms
(`(c ? a : b) & m` becomes `c ? a & m : b & m`, and so on up the expression). A display-list builder's load-block
packet clamped its texel count that way: the clamp was `lrs > 2047 ? 2047 : lrs` inside `_SHIFTL(MIN(lrs, 2047), 12, 12)`,
the shift and mask moved into both arms (`lui 0x77f; ori 0xf000` for the constant arm, a duplicated `andi/sll` for the
other) and the target's single clamp (`slti v0,v1,0x800; beql v0,zero; addiu v1,zero,0x7ff`, then `andi/sll` once) was
unreachable; written `lrs < 2047 ? lrs : 2047` it folded to MIN_EXPR and the packet went 8847 -> 6667 (one function,
with the other edits of that run held fixed). That the second form folds and the first does not is read in fold-const.c's
COND_EXPR case ("If this is A op B ? A : B, this is either A, B, min (A, B), or max (A, B)"); that the distribution is the
cause of the extra instructions is the measured difference, not a traced pass.

`variants` rewrites a conditional `(A cmp B) ? B : A` (a parenthesised comparison of two operands that are names,
constants, field reads or parenthesised arithmetic, with no call, assignment, `++` or nested `?:`), in the function's
body and in `#define` lines, into the same minimum or maximum in the folding orientation: the arms swapped and the
comparison negated, `(A <= B) ? A : B` for `(A > B) ? B : A`, and the mirrored `(B < A) ? B : A`. Two children per
site at most, up to 4 sites. Negating a comparison is only exact for integers (a NaN compares false both ways), so
operands that name a float local or a float literal are left alone."""
import re

from .csource import find

FAMILY = 'ternary_min_max_orientation'
FAMILIES = (FAMILY,)
LIMIT = 4
NEGATE = {'>': '<=', '>=': '<', '<': '>=', '<=': '>'}
MIRROR = {'>': '<', '>=': '<=', '<': '>', '<=': '>='}
COMPARE = re.compile(r'^(?P<a>.+?)\s*(?P<op><=|>=|<|>)\s*(?P<b>.+)$', re.S)
FLOAT = re.compile(r'\b(?:f32|f64|float|double)\b|\d\.\d|\d[fF]\b')
BAD = re.compile(r'\+\+|--|[^=!<>]=[^=]|\w\s*\(|\?|:|&&|\|\|')


def _balanced(text, at):
    """The index just past the group that opens at `at` ('(' or '[')."""
    depth = 0
    for index in range(at, len(text)):
        depth += text[index] in '([' ; depth -= text[index] in ')]'
        if depth == 0:
            return index + 1
    return None


def _strip(operand):
    operand = operand.strip()
    while operand.startswith('(') and _balanced(operand, 0) == len(operand):
        operand = operand[1:-1].strip()
    return re.sub(r'\s+', ' ', operand)


def _simple(operand):
    return bool(operand) and not BAD.search(operand) and not FLOAT.search(operand)


def _arm_end(text, at):
    """The end of the arm that starts at `at`: the first `:`, `)`, `;` or `,` outside any brackets."""
    depth = 0
    for index in range(at, len(text)):
        char = text[index]
        if char in '([':
            depth += 1
        elif char in ')]':
            if depth == 0:
                return index
            depth -= 1
        elif depth == 0 and char in ':;,':
            return index
    return len(text)


def _sites(clean, start, end):
    """(from, to, A, op, B) for each `(A op B) ? B : A` in clean[start:end]."""
    found = []
    for mark in re.finditer(r'\?', clean[start:end]):
        question = start + mark.start()
        before = clean[start:question].rstrip()
        if not before.endswith(')'):
            continue
        close = start + len(before) - 1
        depth, opening = 0, None
        for index in range(close, start - 1, -1):
            depth += clean[index] == ')'
            depth -= clean[index] == '('
            if depth == 0:
                opening = index
                break
        if opening is None:
            continue
        inner = clean[opening + 1:close].strip()
        hit = COMPARE.match(inner)
        if not hit or not _simple(hit['a']) or not _simple(hit['b']):
            continue
        first_end = _arm_end(clean, question + 1)
        if first_end >= end or clean[first_end] != ':':
            continue
        second_end = _arm_end(clean, first_end + 1)
        a, b = hit['a'].strip(), hit['b'].strip()
        if _strip(clean[question + 1:first_end]) == _strip(b) and _strip(clean[first_end + 1:second_end]) == _strip(a):
            found.append((opening, second_end, a, hit['op'], b))
    return found


def variants(source, name):
    spans = []
    span = find(source, name)
    if span:
        spans.append((span[0], span[1]))
    for line in re.finditer(r'(?m)^[ \t]*#[ \t]*define\b[^\n]*(?:\\\n[^\n]*)*', source):
        spans.append((line.start(), line.end()))
    if not span:
        return []
    out = []
    for start, end in spans:
        for opening, stop, a, op, b in _sites(source, start, end):
            for text in (f'({a} {NEGATE[op]} {b}) ? {a} : {b}', f'({b} {MIRROR[op]} {a}) ? {b} : {a}'):
                out.append(source[:opening] + text + source[stop:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT * 2]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 300,
          'directives': True}
