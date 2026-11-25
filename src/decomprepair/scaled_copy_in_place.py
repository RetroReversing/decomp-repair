"""A scaled copy of a local that nothing reads afterwards, written back into the local.

m2c gives every scaled value a name of its own: `temp_a0_3 = var_a0 * 4;` and then reads `temp_a0_3` in the commands that
follow, with `var_a0` dead. The game's code scaled the variable in place (`a = a * 4;`) and read it again. The two are the
same program and a different set of pseudo registers: with a copy, combine folds a later `temp * 2` into `var * 8` (one
`sll`), and in place the scaled value stays the one the later shift is applied to (`sll 2` then `sll 1`, the target's
two instructions). On a 315-instruction tile-rectangle builder the in-place form was the last edit before 0, after a
staged operand (`arm_operand_pre_stage`): 495 -> 0 together, 655 -> 495 alone.

`variants` takes a statement `T = X * K;` or `T = X << K;` where `T` is a local assigned only there and read only after
it, and `X` is a local nothing reads after the statement: every later mention of `X` is a plain assignment `X = ...;`
(and, when the statement sits in a loop, the first mention of `X` in each enclosing loop's body is a plain assignment
directly in that body, so the next iteration assigns `X` again before it reads it). The statement becomes `X = X * K;`,
the later mentions of `T` become `X`, and `T`'s declaration goes. One proposal per statement (at most 4), and all of them
together. A hypothesis about the compiler's choice; the exact judge decides."""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'scaled_copy_in_place'
FAMILIES = (FAMILY,)
LIMIT = 4

_ID = r'[A-Za-z_]\w*'
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_SCALE = re.compile(rf'(?P<t>{_ID})\s*=\s*(?P<x>{_ID})\s*(?P<op>\*|<<)\s*(?P<k>{_NUMBER})\s*;')


def _mentions(clean, name, start, end):
    return [m for m in re.finditer(rf'(?<![\w.]){re.escape(name)}\b', clean[start:end])]


def _plain_assignment(clean, start, end, at, name):
    """True when the mention of `name` at `at` is the whole left side of a plain `=` (not `==`, not `+=`)."""
    return re.match(r'\s*=(?!=)', clean[at + len(name):end]) is not None and not re.search(r'(?:->|\.|&|\*)\s*$', clean[start:at])


def _loops(clean, opening, position):
    """(open, close) of every loop body that holds `position`, innermost last."""
    found = []
    depth_stack = []
    for index in range(opening, position):
        if clean[index] == '{':
            depth_stack.append(index)
        elif clean[index] == '}' and depth_stack:
            depth_stack.pop()
    for brace in depth_stack:
        head = clean[:brace].rstrip()
        loop = head.endswith('do')
        if head.endswith(')'):
            depth = 0
            for index in range(len(head) - 1, -1, -1):
                depth += head[index] == ')'
                depth -= head[index] == '('
                if depth == 0:
                    loop = re.search(r'\b(?:while|for)\s*$', head[:index]) is not None
                    break
        if loop:
            ending = close(clean, brace, '{', '}')
            if ending:
                found.append((brace, ending))
    return found


def _python_directly_in(clean, block, at):
    """True when `at` is in the block's own statements, not in a block nested in it."""
    depth = 0
    for index in range(block[0] + 1, at):
        depth += clean[index] == '{'
        depth -= clean[index] == '}'
    return depth == 0


_directly_in = _python_directly_in
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _directly_in(clean, block, at):
        found = _scan.brace_balance(clean, block[0] + 1, at)
        if found is not NotImplemented:
            return found == 0
        return _python_directly_in(clean, block, at)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    function = clean[opening:end]
    sites = []
    for hit in _SCALE.finditer(clean, opening + 1, end):
        t, x = hit['t'], hit['x']
        if t == x:
            continue
        declared = {n: re.search(rf'(?m)^[ \t]*(?:register[ \t]+)?(?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*[ \t]+{re.escape(n)}[ \t]*;[ \t]*\n', function)
                    for n in (t, x)}
        if not declared[t] or not declared[x]:
            continue
        if re.search(rf'&\s*(?:{re.escape(t)}|{re.escape(x)})\b', function):
            continue
        assigned = [m for m in re.finditer(rf'(?<![\w.]){re.escape(t)}\s*=(?!=)', function)]
        if len(assigned) != 1 or opening + assigned[0].start() != hit.start('t'):
            continue
        spans = [(opening + declared[t].start(), opening + declared[t].end())]
        if any(not (opening + m.start() >= hit.end() or opening + m.start() == hit.start('t')
                    or any(lo <= opening + m.start() < hi for lo, hi in spans))
               for m in _mentions(clean, t, opening, end)):
            continue
        later = [m for m in _mentions(clean, x, hit.end(), end)]
        if any(not _plain_assignment(clean, hit.end(), end, hit.end() + m.start(), x) for m in later):
            continue
        safe = True
        loops = _loops(clean, opening, hit.start())
        for block in loops:
            first = next((m for m in _mentions(clean, x, block[0], block[1])), None)
            at = block[0] + first.start() if first else None
            # the first mention is a plain assignment, directly in this loop's body or in the body of an inner loop that
            # also holds the statement: each pass of the loop assigns `x` before anything reads it
            if first is None or not _plain_assignment(clean, block[0], block[1], at, x) \
                    or not any(block[0] <= inner[0] and inner[0] < at < inner[1] and _directly_in(clean, inner, at)
                               for inner in loops):
                safe = False
                break
        if safe:
            sites.append((hit, declared[t]))
    if not sites:
        return []
    sites = sites[:LIMIT]
    out = []
    groups = [sites] if len(sites) > 1 else []
    groups += [[site] for site in sites]
    for group in groups:
        edits = []
        for hit, declaration in group:
            t, x = hit['t'], hit['x']
            edits.append((hit.start(), hit.end(), f'{x} = {x} {hit["op"]} {hit["k"]};'))
            edits.append((opening + declaration.start(), opening + declaration.end(), ''))
            for m in _mentions(clean, t, hit.end(), end):
                edits.append((hit.end() + m.start(), hit.end() + m.end(), x))
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
