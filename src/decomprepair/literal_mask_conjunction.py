"""A mask written as the AND of two literals, where one of them is the mask the game used.

`x & (0xFF0000 & 0xFFFFu)` is `x & 0`: the middle byte of a colour word that the target masks out with
`lui $v0, 0xff; and $v0, $s2, $v0` is gone from the source, so the candidate stores one byte fewer than the target and
every later step works around the hole. Nobody writes the conjunction of two constants; it is what is left when a
rewrite (or a draft chain) spliced a width mask into an existing mask. The compiler folds it before any pass sees it,
so the exact judge only sees a function with a missing term, and no family offers the term back.

The fix alone is worse than the hole (`2325 -> 2840` here): the term comes back at the end of a chain whose other terms
were written around the missing one (`(x & 0xFF00) | (hi(x) | (x & 0xFF0000))`), and GCC 2.7.2's `|` chain keeps the
source's order into the schedule. So the repair is offered with the order of the chain it sits in.

`variants` finds `& (A & B)` with two integer literals (an optional `u` suffix) whose conjunction is neither of them. For
each, the literal kept is `A` or `B`, and the enclosing chain of `|` operands (the outermost parenthesised group that is
only `|`, nested groups flattened) is written in every order of up to 3 terms, the original order first: a child per
literal and order. At most 12 proposals. In a 313-instruction display-list loop (KMC GCC 2.7.2, `-O2 -G0 -mips3`)
the `& 0xFF0000` term was the missing byte and the chain `(x >> 0x18 << 0x18) | (x & 0xFF0000) | (x & 0xFF00)` the
order: 2325 with the conjunction, 2155 with the one child, and the library's chain then reached 0 (it stopped at 670
with the conjunction). The orders and the literal are hypotheses; the exact judge decides."""
import itertools
import re

from .csource import find

FAMILY = 'literal_mask_conjunction'
FAMILIES = (FAMILY,)
LIMIT = 12
TERMS = 3

_NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*'
_PAIR = re.compile(rf'&\s*\(\s*(?P<a>{_NUMBER})\s*&\s*(?P<b>{_NUMBER})\s*\)')


def _value(text):
    return int(re.sub(r'[uUlL]+$', '', text), 0)


def _python_matching(text, opening):
    depth = 0
    for at in range(opening, len(text)):
        depth += (text[at] == '(') - (text[at] == ')')
        if depth == 0:
            return at
    return -1


_matching = _python_matching
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _matching(text, opening):
        found = _scan.close_every(text, opening, '(', ')', False, -1)
        return _python_matching(text, opening) if found is NotImplemented else found


def _split(text):
    """The top-level `|` operands of a text (a `||` is not one), or [text]."""
    parts, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if char == '|' and depth == 0 and text[at - 1:at] != '|' and text[at + 1:at + 2] != '|':
            parts.append(text[start:at])
            start = at + 1
    parts.append(text[start:])
    return [part.strip() for part in parts]


def _flatten(text):
    """The terms of a chain of `|` operands, nested parenthesised chains opened; None unless it is a chain."""
    parts = _split(text)
    if len(parts) == 1:
        stripped = text.strip()
        if stripped.startswith('(') and _matching(stripped, 0) == len(stripped) - 1:
            return _flatten(stripped[1:-1])
        return None
    terms = []
    for part in parts:
        inner = _flatten(part)
        terms += inner if inner else [part]
    return terms


def _enclosing_chain(text, at):
    """The outermost parenthesised group around `at` that is only a chain of `|` operands: (start, end, terms)."""
    best = None
    stack = []
    for index, char in enumerate(text[:at]):
        if char == '(':
            stack.append(index)
        elif char == ')' and stack:
            stack.pop()
    for opening in reversed(stack):
        closing = _matching(text, opening)
        if closing < at:
            continue
        terms = _flatten(text[opening + 1:closing])
        if terms and len(terms) >= 2:
            best = (opening + 1, closing, terms)
    return best


def _statement_chain(text, at):
    """The chain of `|` operands that is the whole value of the statement around `at` (a `return` or an assignment)."""
    depth, start = 0, 0
    for index in range(at - 1, -1, -1):
        depth += (text[index] == ')') - (text[index] == '(')
        if depth <= 0 and text[index] in ';{}':
            start = index + 1
            break
    depth, end = 0, len(text)
    for index in range(at, len(text)):
        depth += (text[index] == '(') - (text[index] == ')')
        if depth <= 0 and text[index] == ';':
            end = index
            break
    statement = text[start:end]
    word = re.match(r'\s*return\b', statement)
    if word:
        begin = word.end()
    else:
        marks = [mark.end() for mark in re.finditer(r'(?<![=!<>|&+\-*/%^])=(?!=)', statement)
                 if statement[:mark.start()].count('(') == statement[:mark.start()].count(')')]
        if not marks:
            return None
        begin = marks[-1]
    expression = statement[begin:]
    terms = _flatten(expression)
    if not terms or len(terms) < 2:
        return None
    return start + begin + len(expression) - len(expression.lstrip()), start + begin + len(expression.rstrip()), terms


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    out = []
    for hit in _PAIR.finditer(text):
        a, b = _value(hit['a']), _value(hit['b'])
        if a & b in (a, b):
            continue
        for keep in (hit['a'], hit['b']):
            fixed = text[:hit.start()] + f'& {keep}' + text[hit.end():]
            here = hit.start() + len(f'& {keep}')
            chain = _enclosing_chain(fixed, here) or _statement_chain(fixed, here)
            orders = [fixed]
            if chain and len(chain[2]) <= TERMS:
                start, end, terms = chain
                # The terms as they now read (the fixed text re-flattened), every order of them.
                for order in itertools.permutations(range(len(terms))):
                    orders.append(fixed[:start] + ' | '.join(terms[k] for k in order) + fixed[end:])
            for child in orders:
                out.append((FAMILY, source[:span[0]] + child + source[span[1]:]))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 99}  # the registry: no caller wiring (registry.py)
