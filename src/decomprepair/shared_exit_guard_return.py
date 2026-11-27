"""A nested test whose two paths reach one `return`, written as the early return it was.

m2c writes a guard that leaves the function from inside other tests as a block that jumps to the shared exit, with
the same jump after it:

    if (target->type != NONE) {
        ...the rest...
        goto block_17;
    }
    goto block_17;
    ...
    block_17:
        return NULL;

The source had `if (target->type == NONE) { return NULL; }` and the rest after it. The two are one program, but not
one compile: on a 123-instruction N64 hit test (SN GCC 2.8.1 -O2) the target loads `target->type` again to index a
table, and only the early `return` kept that second load; the block form (and an early `goto` to the same label) read
it once (100 -> 0). That cse stops at the return's own jump is a hypothesis from that match, not read from the
compiler's source.

shared_exit_guard_return
    `if (C) { BODY goto L; } goto L;`, where `L:` is followed (after other labels) by `return V;`, becomes
    `if (!C) { return V; } BODY goto L;`. One child per such test. Refused when BODY declares a local.
"""
import re

from .c_scan import close
from .early_return_guard_block import _negate
from .integer_repair_support import IDENT, edit, view

FAMILY = 'shared_exit_guard_return'
FAMILIES = (FAMILY,)
LIMIT = 6

_IF = re.compile(r'(?<![\w.>])if\s*\(')
_OPEN = re.compile(r'\s*\{')
_GOTO = re.compile(rf'\s*goto\s+({IDENT})\s*;')
_LAST_GOTO = re.compile(rf'(?<![\w.>])goto\s+({IDENT})\s*;\s*$')
_DECLARATION = re.compile(rf'(?:^|[;{{}}])\s*(?!(?:return|goto|else|case)\b)(?:{IDENT}\s+)+(?:\*\s*)*{IDENT}\s*(?:[=;\[])')


def _exit_value(clean, lo, hi, label):
    """What `label:` returns: the value of the `return` right after it and any further labels."""
    found = re.search(rf'(?<![\w.>]){label}\s*:(?!:)(?:\s*;|\s*(?!default\b){IDENT}\s*:(?!:))*\s*'
                      rf'return\s+(-?\w+)\s*;', clean[lo:hi])
    return found[1] if found else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, close(part.clean, part.opening)
    out = []
    for found in _IF.finditer(clean, lo, hi):
        paren = found.end() - 1
        paren_end = close(clean, paren, '(', ')')
        block = _OPEN.match(clean, paren_end + 1) if paren_end >= 0 else None
        if not block:
            continue
        opening = block.end() - 1
        closing = close(clean, opening)
        after = _GOTO.match(clean, closing + 1) if closing >= 0 else None
        if not after:
            continue
        body = clean[opening + 1:closing]
        last = _LAST_GOTO.search(body)
        label = after[1]
        value = _exit_value(clean, lo, hi, label)
        if not last or last[1] != label or value is None or _DECLARATION.search(body):
            continue
        indent = source[source.rfind('\n', 0, found.start()) + 1:found.start()]
        indent = indent if not indent.strip() else ''
        condition = _negate(source[paren + 1:paren_end])
        text = (f'if ({condition}) {{\n{indent}    return {value};\n{indent}}}'
                f'{source[opening + 1:closing].rstrip()}')
        out.append((FAMILY, edit(source, [(found.start(), after.end(), text)])))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
