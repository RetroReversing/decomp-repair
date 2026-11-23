"""A pointer parameter copied into a local inside each arm of the `if` that tests it, the arms' loads through the copy.

The target moves the parameter into an argument register in the branch's delay slot, then loads through that register
in both arms, and passes it on to a call after the join:

    beqz $v0, L; move $a0, $s0       (the copy, in the delay slot)
    lw $a1, 0x84($a0)                (each arm loads through the copy)
    ...
    jal f                            (the copy is the call's first argument)

m2c's draft (`if (arg0->c0 != 0) x = arg0->84; else x = arg0->88; f(arg0, x, 0x100);`) loads through the saved
register `$s0` instead, two register rows away from the target. Copying the parameter once above the `if` doesn't give
it either (185 rows: the copy is then a pseudo of its own, live across the test, and takes the register the test
needed). The source that matches writes the copy at the top of *each* arm, the condition still reading the parameter,
and every later use through the copy: `void *p; if (arg0->c0 != 0) { p = arg0; x = p->84; } else { p = arg0;
x = p->88; } f(p, x, 0x100);`. Hypothesis (not checked in the compiler's source): the two sets of `p` are one pseudo
that the join makes live only from the arms on, so it is allocated to `$a0` (its copy preference for the call) and
reorg fills each arm's leading `move` into the branch's delay slot.

A KMC GCC 2.7.2 N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 13 instructions, a call, then a two-way
load picking the second argument of another call) went 10 -> 0 with that one rewrite.

`variants`, for each pointer parameter the body never writes (no assignment, increment or `&`), takes each
`if (cond) { ... } else { ... }` (braced arms, a plain `else`, not an `else if`) whose condition and both arms name
the parameter, and whose arms do not start with a declaration. It declares a local of the parameter's type at the top
of the body, puts `p = arg;` at the top of each arm, and reads the parameter through the copy in the arms; a second
child also reads it through the copy after the `if`, to the end of the block holding it (the copy equals the parameter
on every path from the arms on, because nothing writes either). The condition keeps the parameter. At most 6
children."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'arm_pointer_parameter_copy'
FAMILIES = (FAMILY,)
LIMIT = 6
_IF = re.compile(r'(?<![\w.])if\s*\(')
_ELSE = re.compile(r'\s*else\s*\{')
_KEYWORDS = {'return', 'goto', 'break', 'continue', 'if', 'else', 'while', 'do', 'for', 'switch', 'case', 'default',
             'sizeof'}
_TYPES = r'(?:const|volatile|unsigned|signed|struct|union|enum|static|register|extern)\b'


def _parameters(part):
    """[(name, type)] of the definition's pointer parameters."""
    head = part.clean[:part.opening]
    if '(' not in head or ')' not in head:
        return []
    signature = part.source[head.rindex('(') + 1:head.rindex(')')]
    out = []
    for piece in signature.split(','):
        found = re.fullmatch(rf'\s*(?P<type>[\w\s]+?\s*\*[\s*]*)(?P<name>{IDENT})\s*', piece)
        if found:
            out.append((found['name'], re.sub(r'\s+', ' ', found['type']).strip()))
    return out


def _uses(text, parameter, start=0, end=None):
    return [hit.start() for hit in re.finditer(rf'(?<![\w.>]){re.escape(parameter)}\b', text[start:end])]


def _written(body, parameter):
    """Whether the body assigns, increments or takes the address of `parameter` (then a copy of it may differ)."""
    name = re.escape(parameter)
    return bool(re.search(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body)
                or re.search(rf'(?:\+\+|--)\s*{name}\b|(?<![\w.>]){name}\s*(?:\+\+|--)', body)
                or re.search(rf'&\s*{name}\b(?!\s*[-.\[])', body))


def _declares(text):
    """Whether the block body `text` starts with a declaration (a statement may not come before one in C89)."""
    first = text.lstrip()
    if re.match(_TYPES, first):
        return True
    words = re.match(rf'({IDENT})[\s*]+({IDENT})\s*[;=\[,]', first)
    return bool(words) and words[1] not in _KEYWORDS


def _fresh(clean, stem):
    name, number = stem, 0
    while re.search(rf'\b{re.escape(name)}\b', clean):
        number += 1
        name = f'{stem}{number}'
    return name


def _enclosing_end(clean, position, opening, end):
    """The end (the closing brace's position) of the innermost block of the body that holds `position`."""
    depth, at = 0, position
    while at > opening:
        at -= 1
        if clean[at] == '}':
            depth += 1
        elif clean[at] == '{':
            if depth == 0:
                break
            depth -= 1
    closing = close(clean, at, '{', '}') if at > opening else end
    return (closing or end) - 1


def _replace(clean, parameter, copy, start, end):
    return [(start + at, start + at + len(parameter), copy) for at in _uses(clean, parameter, start, end)]


def variants(source, name):
    """Proposals: a pointer parameter copied at the top of each arm of the `if` that tests it."""
    part = view(source, name)
    if not part:
        return []
    clean, body_at = part.clean, part.opening + 1
    body = clean[body_at:part.end]
    out = []
    for parameter, kind in _parameters(part):
        if not _uses(body, parameter) or _written(body, parameter):
            continue
        for hit in _IF.finditer(clean, body_at, part.end):
            if re.search(r'\belse\s*$', clean[body_at:hit.start()]):
                continue  # an `else if`: its arms are not all the paths to the join
            condition_end = close(clean, hit.end() - 1, '(', ')')
            if not condition_end or not _uses(clean, parameter, hit.end(), condition_end - 1):
                continue
            then_open = re.match(r'\s*\{', clean[condition_end:])
            if not then_open:
                continue
            then_at = condition_end + then_open.end() - 1
            then_end = close(clean, then_at, '{', '}')
            other = _ELSE.match(clean, then_end) if then_end else None
            if not other:
                continue
            else_at = other.end() - 1
            else_end = close(clean, else_at, '{', '}')
            if not else_end:
                continue
            arms = ((then_at, then_end), (else_at, else_end))
            if any(not _uses(clean, parameter, a + 1, b - 1) or _declares(clean[a + 1:b - 1]) for a, b in arms):
                continue
            copy = _fresh(clean, 'p')
            stars = kind.count('*')
            declare = [(body_at, body_at, f"\n    {kind.replace('*', '').strip()} {'*' * stars}{copy};")]
            changes = declare[:]
            for a, b in arms:
                changes.append((a + 1, a + 1, f'\n        {copy} = {parameter};'))
                changes += _replace(clean, parameter, copy, a + 1, b - 1)
            block_end = _enclosing_end(clean, hit.start(), part.opening, part.end)
            after = _replace(clean, parameter, copy, else_end, block_end)
            if after:  # the full rewrite (arms and after the join) first: it was the one that matched
                out.append(edit(source, changes + after))
            out.append(edit(source, changes))
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
