"""tail_exit_guard_first: a closing failure tail written as the guard in front of the function's work.

`if (C) { WORK; return X; } FAIL; return Y;` becomes `if (!C) { FAIL; return Y; } WORK; return X;`.

Matched shape: a Nintendo 64 display-list loader built by SN-N64 2.81 (`-G0 -mips3 -O2 -mfp64`) that returns the
advanced command pointer, and a failure path that clears the caller's flag and returns the pointer unchanged. An
earlier guard does the same two things. The target keeps both failure blocks apart, the second one last, falling into
the epilogue. With the work inside the `if` and the failure after it, the compiler moved the failure block up beside
the first guard and merged the two (`beqz`/`bnez` into one shared block): 1195. With the failure written as a guard
before the work, the layout was the target's: 220. (Reading the jump2 dump shows the two blocks present until the
last jump pass merged them; that the block move before it is jump.c's is a hypothesis, not read from its source.)

`guard_shape` makes this exchange only when nothing but the `return` follows the `if`; the other guard families move
a lone return, or invert an `if` that has no failure statements of its own. Here the statements travel with the exit.

Pure text rewrite: nothing is compiled, and the exact judge decides the child.
"""
import re

from .early_return_guard_block import _negate
from .guard_shape_repairs import _guards
from .integer_repair_support import IDENT, edit, view

FAMILY = 'tail_exit_guard_first'
FAMILIES = (FAMILY,)

_EXIT = re.compile(r'\breturn\b(?P<value>[^;{}]*);\s*$')
_DECLARATION = re.compile(rf'(?:^|[;{{}}])\s*(?!return\b|if\b|else\b|goto\b)(?:{IDENT}\s+)+(?:\*\s*)*{IDENT}\s*(?:[=;,\[])')
_JUMPS = re.compile(rf'\bgoto\b|(?:^|[;{{}}])\s*(?!case\b|default\b){IDENT}\s*:(?!:)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    stop = clean.rfind('}', 0, part.end)
    result = []
    for start, condition, opening, after in _guards(part):
        work, fail = clean[opening + 1:after - 1], clean[after:stop]
        # The tail is straight-line: with a block of its own it is more of the function than a way out.
        if re.match(r'\s*else\b', fail) or '{' in fail or '}' in fail or _JUMPS.search(work + fail):
            continue
        leaves, closes = _EXIT.search(work), _EXIT.search(fail)
        # Both sides leave the function, and the tail has something to do besides leaving (guard_shape has the rest).
        if not leaves or not closes or not fail[:closes.start()].strip() or _DECLARATION.search(fail):
            continue
        # A `return` inside WORK's own nested block is fine; the last statement must be the one at WORK's level.
        if work[:leaves.start()].count('{') != work[:leaves.start()].count('}'):
            continue
        line = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:start])[0]
        inner = indent + '    '
        moved = '\n'.join(inner + row.strip() for row in source[after:stop].split('\n') if row.strip())
        body = source[opening + 1:after - 1].strip('\n').rstrip()
        if _DECLARATION.search(work):
            # WORK's declarations stay in a block of their own.
            body = f'{indent}{{\n{body}\n{indent}}}'
        else:
            body = '\n'.join(row[4:] if row.startswith(inner) else row for row in body.split('\n'))
        text = f'if ({_negate(condition)}) {{\n{moved}\n{indent}}}\n{body}\n'
        result.append((FAMILY, edit(source, [(start, stop, text)])))
    return result[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
