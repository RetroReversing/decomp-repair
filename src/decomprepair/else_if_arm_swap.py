"""An `if (a < b) { A } else { B }` written with the opposite test and the arms in the other order.

GCC branches over the `then` arm to the `else` arm, so which arm is laid out first (and which one a delay slot or a
branch-likely takes an insn from) follows the test's polarity. The target of one chain (`bnez` on `h - 1 < t` into the
out-of-line arm `t + 1 - h`, the plain `v = t` falling through) was written the other way round: `else if (t <= h - 1)
{ v = t; } else { t + 1 - h }` (1300 -> 905 in one 242-instruction heightmap filter, KMC GCC 2.7.2, with the other
edits of that run; 260 on its own at the end of the run).

A proposal takes `if (L op R) {A} else {B}` (both arms braced, a single comparison with no `&&`, `||` or `!`) and writes
`if (L inverse R) {B} else {A}`, and again with the operands exchanged (`R mirror L`). It also takes the last `else if` of a chain. At
most 6 proposals; the judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'else_if_arm_swap'
FAMILIES = (FAMILY,)
LIMIT = 6

_INVERSE = {'<': '>=', '<=': '>', '>': '<=', '>=': '<', '==': '!=', '!=': '=='}
_MIRROR = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '==': '==', '!=': '!='}
_TEST = re.compile(r'if[ \t]*\((?P<l>[^&|!()\n;{}=<>]*(?:\([^()\n]*\)[^&|!()\n;{}=<>]*)*?)[ \t]*(?P<op><=|>=|==|!=|<|>)[ \t]*(?P<r>[^&|!()\n;{}=<>]*(?:\([^()\n]*\)[^&|!()\n;{}=<>]*)*)\)[ \t]*\{')


def _close(text, at):
    depth = 0
    for position in range(at, len(text)):
        depth += text[position] == '{'
        depth -= text[position] == '}'
        if depth == 0:
            return position
    return None


def variants(source, name):
    """Proposals: a two-armed `if` with the inverse test and the arms exchanged."""
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    for hit in _TEST.finditer(clean, part.opening + 1, part.end):
        first = hit.end() - 1
        then_end = _close(clean, first)
        other = re.compile(r'[ \t\n]*else[ \t\n]*\{').match(clean, then_end + 1) if then_end else None
        if not other:
            continue
        second = other.end() - 1
        else_end = _close(clean, second)
        if else_end is None:
            continue
        then_body, else_body = source[first + 1:then_end], source[second + 1:else_end]
        left, right = hit['l'].strip(), hit['r'].strip()
        if not left or not right:
            continue
        for tests in (f"{left} {_INVERSE[hit['op']]} {right}", f"{right} {_MIRROR[_INVERSE[hit['op']]]} {left}"):
            text = f"if ({tests}) {{{else_body}}} else {{{then_body}}}"
            out.append((FAMILY, edit(source, [(hit.start(), else_end + 1, text)])))
            if len(out) >= LIMIT:
                return list(dict.fromkeys(out))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 94}  # the registry: no caller wiring (registry.py)
