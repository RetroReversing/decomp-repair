"""A guarded store outside every loop wrapped in one one-shot scope, for the weight it adds to the locals it names.

`do { S } while (0);` is one loop more round `S` to flow.c, which counts every reference a statement makes once more
for each loop it sits in, so the pseudos `S` names rank higher in global.c's allocation order and in local-alloc's, at
no instruction cost. `statement_scope_weight` does this for the statements of a loop body and `local_weight_ladder`
for every statement of one named local; neither reaches a plain `if (c) dst = v;` in straight-line code, which is
where a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update needed it. Three guarded stores of one
halfword local (`if (!fixed) s = v; if (v < s) s = v; if (v - s >= limit) s = v;`) left that local a register ahead of
the sign-extended copy the later compares make of it, because the local's loop sum made it rank above its own copy
and the loop bounds. Wrapping the third guarded store in a scope raised the copy and the bound's rank by one weight and
gave the target's `$a1` / `$a0` (270 -> 205, 13 differing rows fewer).

store_guard_scope
    `if (c) dst = v;` (no `else`, no `break`/`continue`/`return`/label, not inside a loop) becomes `do { if (c) dst = v; }
    while (0);`, one child per such statement. The wrapper is scaffolding no developer wrote; polishing removes it.
    Hypothesis from the match, not from the compiler source: the references count by loop depth in flow.c.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'store_guard_scope'
FAMILIES = (FAMILY,)
LIMIT = 12
def _python_loop_header(text):
    """True when `text` (what precedes a `{` or a statement) ends with `for (...)`, `while (...)` or `do`."""
    text = text.rstrip()
    if re.search(r'\bdo$', text):
        return True
    if not text.endswith(')'):
        return False
    depth = 0
    for position in range(len(text) - 1, -1, -1):
        depth += (text[position] == ')') - (text[position] == '(')
        if depth == 0:
            return re.search(r'\b(?:for|while)\s*$', text[:position]) is not None
    return False


_loop_header = _python_loop_header
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _loop_header(text):
        text = text.rstrip()
        if re.search(r'\bdo$', text):
            return True
        if not text.endswith(')'):
            return False
        position = _scan.open_every(text, len(text) - 1, '(', ')', None)
        if position is None:
            return False
        return re.search(r'\b(?:for|while)\s*$', text[:position]) is not None


def _inside_loop(clean, position, low):
    stack = []
    for m in re.finditer(r'[{}]', clean[low:position]):
        if m[0] == '{':
            stack.append(low + m.start())
        elif stack:
            stack.pop()
    return any(_loop_header(clean[:start]) for start in stack[1:])


def _children(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    clean, result = part.clean, []
    for head in re.finditer(r'\bif\s*\(', clean[part.opening + 1:part.end]):
        start = part.opening + 1 + head.start()
        if (re.search(r'\belse\s*$', clean[:start]) or _inside_loop(clean, start, part.opening)
                or _loop_header(clean[:start])):
            continue
        stop = close(clean, start + head.group(0).index('('))
        if stop is None:
            continue
        stmt = re.compile(r'\s*[^;{}]+;').match(clean, stop)
        if not stmt or re.search(r'\b(?:break|continue|return|goto|case|default)\b', clean[stop:stmt.end()]):
            continue
        if re.match(r'\s*else\b', clean[stmt.end():]) or '=' not in clean[stop:stmt.end()]:
            continue
        line = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:start])[0]
        if source[line:start].strip():
            continue
        body = source[start:stmt.end()]
        text = f'do {{\n{indent}    {body.strip()}\n{indent}}} while (0);'.replace(f'\n{indent}    ' + body.strip(), f'\n{indent}    ' + body.strip().replace('\n', '\n    '))
        result.append((FAMILY, edit(source, [(start, stmt.end(), text)])))
    return result[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
