"""A float sum passed to a call that sits in `do { } while (0)` wrappers: the sum in an `f32` local set before them.

    do { do { do {                                     { f32 sx = (2.0f * cx - 16.0f) + x;
        f(p, (u16) (u32) (x + (2.0f * cx - 16.0f)));     do { do {
    } while (0); } while (0); } while (0);       ->        f(p, (u16) (u32) sx);
                                                         } while (0); } while (0); }

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`). flow.c weighs each reference by its loop depth, and an empty
`do { } while (0)` counts as a loop, so the same three float temporaries (`2.0f * cx`, the difference, `(f32) x`)
get different priorities inside the wrappers than in a sibling arm without them: local-alloc.c's
`floor_log2 (refs) * refs / life` jumps when the weighted reference count passes a power of two, the difference's
quantity loses to the conversion's and the two take each other's registers (`$f0`/`$f2` swapped in four rows).
The wrappers are still needed for the call's other arguments (the arm's address pointers keep their saved registers
through the same weights), so the sum moves out of them into a local of its own, set before the wrapper at the
weight of the arm, with its operands in the sibling arm's order. Measured with the exact judge on a 534-instruction
menu builder whose third switch arm had three wrappers: 140 -> 120 (two wrappers kept, the difference first),
125 with the operands as written, 155 with three wrappers.

Children, for each statement that is one call wrapped in one or more `do { } while (0)` whose argument list holds
`(T) (T2) (A + B)` or `(T) (A + B)` with a float literal in A or B: the sum as `f32` local `sx` (a fresh name) set
before the wrappers, at the same wrapper depth and at one level less, each with the sum's operands as written and
swapped. The judge decides every child.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'wrapped_call_float_sum_local'
FAMILIES = (FAMILY,)
_OPEN = re.compile(r'(?:do\s*\{\s*)+')
_FLOAT = re.compile(r'\d+\.\d*f\b|\d+\.\d*[eE][-+]?\d+f\b')


def _closing(text, at):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == '(') - (text[i] == ')')
        if depth == 0:
            return i
    return -1


def _top_plus(text):
    """The index of `text`'s one top-level `+` (not inside parentheses), or None."""
    depth, at = 0, []
    for i, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if depth == 0 and char == '+' and text[i - 1:i] not in ('+', 'e', 'E') and text[i + 1:i + 2] != '+':
            at.append(i)
    return at[0] if len(at) == 1 else None


def _fresh(clean):
    for name in ('sx', 'sum', 'fx', 'fsum'):
        if not re.search(rf'\b{name}\b', clean):
            return name
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    pattern = re.compile(r'(?P<open>(?:do\s*\{\s*)+)(?P<call>' + IDENT + r'\s*\((?P<args>[^;{}]*)\)\s*;)'
                         r'(?P<close>(?:\s*\}\s*while\s*\(\s*0\s*\)\s*;)+)')
    for hit in pattern.finditer(clean, part.opening, part.end):
        depth = hit['open'].count('do')
        if hit['close'].count('while') != depth:
            continue
        local = _fresh(clean)
        if not local:
            break
        args = hit['args']
        for cast in re.finditer(r'(?:\(\s*\w+\s*\)\s*){1,2}\(', args):
            start = hit.start('args') + cast.end() - 1
            end = _closing(clean, start)
            inner = source[start + 1:end]
            if '?' in inner or not _FLOAT.search(inner):
                continue
            cut = _top_plus(clean[start + 1:end])
            if cut is None:
                continue
            left, right = inner[:cut].strip(), inner[cut + 1:].strip()
            call = source[hit.start('call'):start] + local + source[end + 1:hit.end('call')]
            for a, b in ((left, right), (right, left)):
                for level in sorted({depth, max(depth - 1, 1)}, reverse=True):
                    wrapped = 'do { ' * level + call + ' } while (0);' * level
                    text = f'{{ f32 {local} = {a} + {b}; {wrapped} }}'
                    out.append(source[:hit.start()] + text + source[hit.end():])
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
