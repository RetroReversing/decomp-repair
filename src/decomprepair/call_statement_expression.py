"""A store through a computed address whose value contains a call: the call written as a GNU statement expression.

GCC 2.7 expands the calls of an assignment's right side before it works out the left side's address
(`preexpand_calls`, so no address is held across the call). A target that holds the element addresses in saved registers
across the call, one `sll`/`addu` before the `jal` for each store, was written so that the call was not expanded
early: `({ call(); })` is expanded where it stands, after the address (hypothesis about the source: a macro; that the
statement expression gives the target's order is measured).

Measured on a 150-instruction N64 function (KMC GCC 2.7.2, `-G0 -mips3 -O1`) that ends with a loop storing one
sine-scaled halfword into two rows of a vertex array:

    verts[i].ob[2] = verts[i + 8].ob[2] = __sinf(angle) * scale[i];           /* 1817: the addresses after the call */
    verts[i].ob[2] = verts[i + 8].ob[2] = ({ __sinf(angle); }) * scale[i];    /* 0 */

A cast, a comma expression, a temporary for the value and a pointer local for the element did not give the target.

One child per such statement with every call in it wrapped, and one with all such statements wrapped when there is more
than one. The program is the same one C allows: the order of the two sides of an assignment is unspecified. GCC only;
other compilers refuse the child."""
import re

from .integer_repair_support import IDENT, view

WRAPPED = 'call_statement_expression'
FAMILIES = (WRAPPED,)
LIMIT = 8
_NOT_CALLS = ('sizeof', 'if', 'for', 'while', 'switch', 'return', 'do', 'else')
_ASSIGN = re.compile(r'(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)')
_CALL = re.compile(rf'(?<![\w.>])({IDENT})\s*\(')


def _statements(clean, begin, end):
    """(start, stop) of each simple statement between `begin` and `end`, at any brace depth, outside `for` headers."""
    start, depth = begin, 0
    for at in range(begin, end):
        char = clean[at]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and char in '{};':
            if char == ';':
                yield start, at
            start = at + 1


def _closing(text, opening):
    depth = 0
    for at in range(opening, len(text)):
        depth += (text[at] == '(') - (text[at] == ')')
        if depth == 0:
            return at
    return None


def _calls(text, offset):
    """(start, end) of each outermost call in `text`, in positions of the whole source."""
    found, covered = [], 0
    for hit in _CALL.finditer(text):
        callee = hit[1]
        if hit.start() < covered or callee in _NOT_CALLS or callee.startswith('M2C_'):
            continue
        closing = _closing(text, hit.end() - 1)
        if closing is None:
            return []
        if re.search(r'\(\{\s*$', text[:hit.start()]):
            return []  # already a statement expression
        found.append((offset + hit.start(), offset + closing + 1))
        covered = closing + 1
    return found


def _sites(part):
    for start, stop in _statements(part.clean, part.opening + 1, part.end - 1):
        text = part.clean[start:stop]
        assigned = _ASSIGN.search(text)
        if not assigned:
            continue
        left = re.sub(r'^\s*(?:(?:case\b[^:]*|default)\s*:\s*)*', '', text[:assigned.start()])
        # the store's address has to be worked out: an element, a field or a pointer's target
        if not re.search(r'\[|->|\.|^\s*\*', left):
            continue
        calls = _calls(text[assigned.end():], start + assigned.end())
        if calls:
            yield calls


def _wrap(source, calls):
    for start, end in sorted(calls, reverse=True):
        source = source[:start] + '({ ' + source[start:end] + '; })' + source[end:]
    return source


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    sites = list(_sites(part))[:LIMIT]
    results = [(WRAPPED, _wrap(source, calls)) for calls in sites]
    if len(sites) > 1:
        results.append((WRAPPED, _wrap(source, [call for calls in sites for call in calls])))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
