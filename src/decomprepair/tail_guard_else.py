"""A void function's `if (c) { A; return; } REST` nested in its last block, written as `if`/`else`.

Matched on an SN64 (sn-n64-281 -O2) sound trigger of 40 instructions: m2c ends the function's last `if` with
`if (G != 0) { G = 0; return; } G = 1;`. The target tests it with `bnel` to the epilogue, the store of 0 in the
annulled delay slot, and falls through into the store of 1: `if (G == 0) { G = 1; } else { G = 0; }` (360 -> 0;
docs: finding "tail-guard-return-is-an-if-else"). `guard_shape` makes this rewrite only for a guard at the
function body's top level; here the block it sits in is itself the function's last statement, so leaving the
function and leaving the block are the same.

tail_guard_else
    The guard's block is an `if` or `else` block, as is every block around it up to the function body, and nothing but
    the rest of an `if`/`else` chain (and a bare `return;`) follows each. `REST` is what follows the guard in its
    block. Two children per guard: the inverted condition with `REST` first, and the condition kept with `A` first.
    A `goto` or a label in `A` or `REST` declines.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, enclosing_block, header_before
from .guard_shape_repairs import opposite
from .integer_repair_support import edit, view

FAMILY = 'tail_guard_else'
FAMILIES = (FAMILY,)
LIMIT = 6
_IF = re.compile(r'\bif\s*\(')
_GOTO = re.compile(r'\bgoto\b|(?m:^\s*(?!case\b|default\b)\w+\s*:(?!:))')


def _conditional(clean, opening):
    """True when the block opening at `opening` belongs to an `if` or an `else`."""
    before = clean[:opening].rstrip()
    if re.search(r'\belse$', before):
        return True
    return header_before(clean, opening).lstrip().startswith(('if', 'else if'))


def _after_chain(clean, position):
    """The offset after every `else` / `else if` block that continues from `position`; None for unbraced arms."""
    while hit := re.compile(r'\s*else\b').match(clean, position):
        position = hit.end()
        if condition := re.compile(r'\s*if\s*\(').match(clean, position):
            position = close(clean, condition.end() - 1, '(', ')') + 1
            if not position:
                return None
        block = re.compile(r'\s*\{').match(clean, position)
        if not block:
            return None
        position = close(clean, block.end() - 1, '{', '}') + 1
        if not position:
            return None
    return position


def _in_tail(clean, opening, body):
    """Whether leaving the block at `opening` runs nothing more of the function (whose body opens at `body`)."""
    while opening != body:
        if not _conditional(clean, opening):
            return False
        after = close(clean, opening, '{', '}')
        after = _after_chain(clean, after + 1) if after >= 0 else None
        if after is None or not re.compile(r'\s*(?:return\s*;\s*)?\}').match(clean, after):
            return False
        opening = enclosing_block(clean, opening, body)
        if opening < 0:
            return False
    return True


def variants(source, name):
    part = view(source, name)
    if not part or part.opening < 0 or len(source) > 128000:
        return []
    clean, body = part.clean, part.opening
    out = []
    for hit in _IF.finditer(clean, body, part.end):
        closing = close(clean, hit.end() - 1, '(', ')')
        block = re.compile(r'\s*\{').match(clean, closing + 1) if closing >= 0 else None
        if not block or re.search(r'\belse\s*$', clean[:hit.start()]):
            continue
        opening = block.end() - 1
        after = close(clean, opening, '{', '}')
        if after < 0:
            continue
        arm = re.fullmatch(r'(.*?)\breturn\s*;\s*', clean[opening + 1:after], re.S)
        outer = enclosing_block(clean, hit.start(), body)
        end = close(clean, outer, '{', '}') if outer > body else -1
        if not arm or end < 0:
            continue
        rest = clean[after + 1:end]
        if (not arm[1].strip() or not rest.strip() or re.match(r'\s*else\b', rest) or _GOTO.search(arm[1] + rest)
                or re.search(r'\breturn\b', arm[1]) or not _in_tail(clean, outer, body)):
            continue
        condition = source[hit.end():closing].strip()
        inverse = opposite(condition)
        if not inverse:
            continue
        indent = re.search(r'[ \t]*$', source[:hit.start()])[0]
        first = source[opening + 1:opening + 1 + len(arm[1])].rstrip()
        second = re.sub(r'(?m)^(?=[ \t]*\S)', '    ', source[after + 1:end].strip('\n').rstrip())
        close_indent = re.search(r'[ \t]*$', source[:end])[0]
        for test, one, two in ((inverse, '\n' + second, first), (condition, first, '\n' + second)):
            text = f'if ({test}) {{{one}\n{indent}}} else {{{two}\n{indent}}}\n{close_indent}'
            out.append((FAMILY, edit(source, [(hit.start(), end, text)])))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
