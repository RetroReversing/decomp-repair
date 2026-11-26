"""A list walk's exit that reads the global it started from again: `v = G; <walk of v>; v = G; if (v ...)`.

Observed (GCC 2.7.2 SN/KMC `-G0 -mips3 -O2`; one function that takes a node off a free list, 210 -> 0): m2c writes the
head read once and tests the walk's result,

    var_v1 = D_80117420;
    if (var_v1 != NULL) { do { var_v1 = M2C_FIELD(var_v1, void **, 0x48); } while (var_v1 != NULL); }
    if (var_v1 != NULL) { D_80117420 = ...; }                      /* draft: the second test is folded away */

and the target has a second `lui`/`lw %lo(D_80117420)` right after the walk, before the second test, and its first
branch jumps to that reload. Written with `var_v1 = D_80117420;` before the second `if`, the compiler no longer knows
the walk left the variable null, keeps both tests and the load (jump optimization threads a branch to a test whose
value it can prove, and a fresh read of a global it can't). Hypothesis (not confirmed in the compiler's source): the
reload makes the second test's operand an unknown value again, so the first test's branch is not redirected to the
return.

Children: the statement `v = G;` (G a global declared outside the function, `v` a local) written once more right
before the first `if (... v ...)` that follows a loop (a `do`/`while`, or an `if` holding one) that assigns `v`, when
the target loads G more often than the source reads it (the `lw %lo(G)` rows of the target's assembly against the
reads in the source; no assembly given: not checked). Only MIPS. A candidate for the exact judge; the judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILIES = ('walk_exit_global_reload',)
FAMILY = FAMILIES[0]
LIMIT = 4
_LOAD = r'\blw\s+\$\w+\s*,\s*%lo\(\s*{}\s*\)'
_ASSIGN = re.compile(r'(?<![\w.>])([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;')
_DO = re.compile(r'do\s*\{')
_WHILE = re.compile(r'while\s*\(')
_IF = re.compile(r'if\s*\(')


def _statement_end(clean, i):
    """The index just past the loop (or `if` holding a loop) starting at `i`, or None for anything else (an `else` arm
    or a statement that is no block)."""
    do = _DO.match(clean, i)
    if do:
        end = close(clean, do.end() - 1, '{', '}')
        tail = re.compile(r'\s*while\s*\(').match(clean, end) if end else None
        if not tail:
            return None
        stop = close(clean, tail.end() - 1)
        semi = re.compile(r'\s*;').match(clean, stop) if stop else None
        return semi.end() if semi else None
    head = _WHILE.match(clean, i) or _IF.match(clean, i)
    if not head:
        return None
    stop = close(clean, head.end() - 1)
    block = re.compile(r'\s*\{').match(clean, stop) if stop else None
    if not block:
        return None
    end = close(clean, block.end() - 1, '{', '}')
    if not end or re.compile(r'\s*else\b').match(clean, end):
        return None
    return end


def _reads(clean, g):
    """How often `g` is read in the text: every mention but a plain store `g = ...`."""
    return len(re.findall(r'\b' + re.escape(g) + r'\b(?!\s*=(?!=))', clean))


def variants(source, name, asm=None):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]]
    body = clean[opening:end]
    kids = []
    for m in _ASSIGN.finditer(clean, opening, end):
        v, g = m[1], m[2]
        if v == g or not re.search(r'\bextern\b[^;{}]*\b' + re.escape(g) + r'\b', outside):
            continue
        if re.search(r'(?m)^[ \t]*(?!return\b|else\b|goto\b)[A-Za-z_]\w*[ \t]+\**[ \t]*' + re.escape(g) + r'\s*[;=\[]', body):
            continue  # a local of the same name
        first = re.compile(r'\s*').match(clean, m.end()).end()
        stop = _statement_end(clean, first)
        if not stop or not re.search(r'\b' + re.escape(v) + r'\s*=(?!=)', clean[first:stop]):
            continue
        after = re.compile(r'\s*').match(clean, stop).end()
        test = _IF.match(clean, after)
        if not test:
            continue
        cond_end = close(clean, test.end() - 1)
        if not cond_end or not re.search(r'\b' + re.escape(v) + r'\b', clean[test.end():cond_end]):
            continue
        if asm:
            loads = len(re.findall(_LOAD.format(re.escape(g)), asm))
            if loads <= _reads(body, g):
                continue
        line = source.rfind('\n', 0, after) + 1
        indent = re.match(r'[ \t]*', source[line:after])[0] if not source[line:after].strip() else ''
        kids.append(source[:after] + f'{v} = {g};\n{indent}' + source[after:])
    return [(FAMILY, k) for k in dict.fromkeys(kids) if k != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
