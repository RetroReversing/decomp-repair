"""A pointer tested for NULL and returned on success, written through a result variable set to NULL first.

A function that returns the object it tested is usually decompiled as

    if (player != NULL && player->type != NONE) {
        ...                                     /* every failure returns NULL */
        return player;
    }
    return NULL;

SN GCC fills the first branch's delay slot with the last register save there. A target that keeps the save before the
branch and clears `$v0` in the slot had a result variable cleared before the test:

    do { result = NULL; } while (0);
    if (player != NULL) {
        if (player->type == NONE) { return NULL; }
        ...
        result = player;                        /* and fall to `return result;` */
    }
    return result;

On a 123-instruction N64 hit test (SN GCC 2.8.1 -O2) the result variable and fence gave `$v0` its early clear (400 ->
370), and the byte copied to the object on the success path, held in the `u8` local the state tests had used, widened
to `s32`, put that copy in the target's register (370 -> 100). The plain assignment without the fence was scheduled
before the register saves. These are measured results of that function, not read from the compiler's source.

null_result_fence
    The rewrite above: `result` cleared inside `do { } while (0)` before the guard, a first-conjunct-only guard with
    the others as an early `return NULL;`, and each `return P;` as `result = P; goto done;`.
null_result_byte_temp
    The same, and the byte store just before a `return P;` (`X = (u8) E;`) routed through a `u8`/`s8` local the
    function already has, declared `s32`: `T = E; result = P; X = T;`. One child per such local.
"""
import re

from .c_scan import close
from .early_return_guard_block import _negate
from .integer_repair_support import IDENT, edit, view

FAMILY = 'null_result_fence'
BYTE = 'null_result_byte_temp'
FAMILIES = (FAMILY, BYTE)
LIMIT = 6

RESULT = '__repair_result'
DONE = '__repair_done'
_IF = re.compile(r'(?<![\w.>])if\s*\(')
_OPEN = re.compile(r'\s*\{')
_OPERATOR = re.compile(r'[()\[\]?]|&&|\|\|')
_TAIL = re.compile(r'\s*return\s+(NULL|0)\s*;\s*$')
_GUARD = re.compile(rf'\(?\s*({IDENT})\s*!=\s*(?:NULL|0)\s*\)?')
_LOCAL = re.compile(rf'(?m)^[ \t]*(u8|s8)\s+({IDENT})\s*;')


def _conjuncts(clean, start, end):
    """The spans of the top-level `&&` operands in `clean[start:end]`; None when a `||` or `?` sits beside them."""
    parts, depth, last = [], 0, start
    for hit in _OPERATOR.finditer(clean, start, end):
        if hit[0] in '([':
            depth += 1
        elif hit[0] in ')]':
            depth -= 1
        elif depth == 0:
            if hit[0] != '&&':
                return None
            parts.append((last, hit.start()))
            last = hit.end()
    return parts + [(last, end)]


def _definition_type(source, clean, opening, name):
    """The return type written before the function's name."""
    head = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:opening]))
    if not head:
        return None
    start = max(clean.rfind(mark, 0, head[-1].start()) for mark in ';}\n') + 1
    kind = ' '.join(source[start:head[-1].start()].replace('static ', '').split())
    return kind if kind and kind != 'void' else None


def _guard(clean, lo, hi):
    """The function's closing `if (P != NULL && ..) { .. } return NULL;` as (if, conditions, opening, closing, tail)."""
    for found in reversed(list(_IF.finditer(clean, lo, hi))):
        paren = found.end() - 1
        paren_end = close(clean, paren, '(', ')')
        block = _OPEN.match(clean, paren_end + 1) if paren_end >= 0 else None
        if not block:
            continue
        opening = block.end() - 1
        closing = close(clean, opening)
        if closing < 0 or not _TAIL.match(clean[closing + 1:hi]):
            continue
        conditions = _conjuncts(clean, paren + 1, paren_end)
        return (found.start(), conditions, opening, closing) if conditions else None
    return None


def _build(source, part, kind, guard, pointer, temp):
    start, conditions, opening, closing = guard
    clean, hi = part.clean, close(part.clean, part.opening)
    indent = source[source.rfind('\n', 0, start) + 1:start]
    returns = list(re.finditer(rf'(?<![\w.>])return\s+{pointer}\s*;', clean[opening:closing]))
    edits = []
    for found in returns:
        at, end = opening + found.start(), opening + found.end()
        pad = source[source.rfind('\n', 0, at) + 1:at]
        pad = pad if not pad.strip() else indent + '    '
        text = f'{RESULT} = {pointer};\n{pad}goto {DONE};'
        if temp:
            store = re.search(r'(?m)^[ \t]*([^;{}\n]*(?:->|\.|\[)[^;{}\n]*?)\s*=\s*\(\s*(?:u8|s8)\s*\)\s*([^;{}\n]+);\s*\Z',
                              source[opening:at])
            if store and temp not in (store[1] + store[2]):
                at = opening + store.start(1)
                text = f'{temp} = {store[2]};\n{pad}{RESULT} = {pointer};\n{pad}{store[1]} = {temp};\n{pad}goto {DONE};'
            elif len(returns) == 1:
                return None
        edits.append((at, end, text))
    first = source[slice(*conditions[0])].strip()
    rest = [source[slice(*span)].strip() for span in conditions[1:]]
    tests = ''.join(f'\n{indent}    if ({_negate(_bare(one))}) {{\n{indent}        return NULL;\n{indent}    }}'
                    for one in rest)
    edits.append((start, opening + 1, f'do {{ {RESULT} = NULL; }} while (0);\n{indent}if ({_bare(first)}) {{{tests}'))
    tail = _TAIL.match(clean[closing + 1:hi])
    edits.append((closing + 1, closing + 1 + tail.end(0), f'\n{DONE}:\n{indent}return {RESULT};\n'))
    brace = part.opening + 1
    edits.append((brace, brace, f'\n    {kind} {RESULT};'))
    if temp:
        declared = _LOCAL.search(clean, part.opening, part.end)
        while declared and declared[2] != temp:
            declared = _LOCAL.search(clean, declared.end(), part.end)
        edits.append((declared.start(1), declared.end(1), 's32'))
    return edit(source, edits)


def _bare(text):
    """`text` without parentheses around the whole of it."""
    while text.startswith('(') and close(text, 0, '(', ')') == len(text) - 1:
        text = text[1:-1].strip()
    return text


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, close(part.clean, part.opening)
    if RESULT in clean:
        return []
    kind = _definition_type(source, clean, part.opening, name)
    guard = _guard(clean, lo, hi)
    if not kind or not guard:
        return []
    start, conditions, opening, closing = guard
    tested = _GUARD.fullmatch(_bare(clean[slice(*conditions[0])].strip()))
    if not tested or not re.search(rf'(?<![\w.>])return\s+{tested[1]}\s*;', clean[opening:closing]):
        return []
    pointer = tested[1]
    out = []
    plain = _build(source, part, kind, guard, pointer, None)
    for local in _LOCAL.finditer(clean, lo, hi):
        child = _build(source, part, kind, guard, pointer, local[2])
        if child and len(out) < LIMIT - 1:
            out.append((BYTE, child))
    return [(FAMILY, plain)] + out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
