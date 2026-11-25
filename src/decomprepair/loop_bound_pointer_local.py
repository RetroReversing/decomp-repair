"""A do-while's bound read through a pointer named at the top of its guard: `if (T[c] != 0) { ..; do { } while (T[c] >= i); }`
as `if (T[c] != 0) { u32 *lim = T + c; ..; do { } while (*lim >= i); }`.

A canonical-code builder's passes count each code length's symbols: `i = 1; if (H[c] != 0) { do { ..; i++; } while
(H[c] >= i); }`, the guard and the inner test reading the same histogram slot. KMC GCC 2.7.2 (`-O2`, N64) makes the
inner test's address a giv of the outer loop either way, but the copy the inner loop tests through is emitted where the
source names it: written as the index, loop.c's copy (`move $a1,$a0`) comes after the inner loop's other pointer set-up;
named as a pointer local first in the guard's block, it comes before it, as the target has it. On a 681-instruction
bit-stream decoder whose other passes already read their bound through such a `lim`, the length pass's bound as one
too was 350 -> 290 (checked on 600 generated streams against a clean transcription); writing the store cursor as an
index at the same time was worse (535), so the pointer is offered alone.

Rewrites a `do { } while (...)` whose condition reads `A[i]` (`A` a pointer local or a global array, `i` not assigned
in the loop), when the do-loop is in a block whose own `if` tests the same `A[i]`: the block gets `T *lim = A + i;` as
its first statement (T the element type from `A`'s declaration) and the condition reads `*lim`. Declines when the block
already names `lim` (or the function's own top level does), or for `volatile`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'loop_bound_pointer_local'
FAMILIES = (FAMILY,)
LIMIT = 6

_TYPE = r'(?:unsigned\s+(?:int|short|char)|s32|u32|s16|u16|s8|u8|int|short|f32)'


def _python_close(text, at, left, right):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == left) - (text[i] == right)
        if depth == 0:
            return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, at, left, right):
        found = _scan.close_every(text, at, left, right, False, None)
        return _python_close(text, at, left, right) if found is NotImplemented else found


def _element_type(source, clean, base):
    found = re.search(rf'(?m)^[ \t]*(?:extern\s+)?({_TYPE})\s+{base}\s*\[[^\]]*\]\s*;', source)
    if found:
        return found.group(1)
    found = re.search(rf'(?m)^[ \t]*({_TYPE})\s*\*\s*{base}\s*;', clean)
    found = found or re.search(rf'[(,]\s*({_TYPE})\s*\*\s*{base}\s*[,)]', clean)  # a parameter
    return found.group(1) if found else None


def _assigned(text, name):
    return re.search(rf'(?<![\w.>])(?:{name}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{name}\b)', text)


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]) or re.search(r'(?m)^  \S[^\n]*\blim\b', clean[lo:hi]):
        return []  # a function-level `lim` (a block of its own may have one: the new one is in another block)
    sites = []
    for guard in re.finditer(rf'\bif\s*\(\s*({IDENT})\s*\[\s*({IDENT})\s*\]\s*!=\s*0\s*\)\s*\{{', clean[lo:hi]):
        base, index = guard.group(1), guard.group(2)
        opening = lo + guard.end() - 1
        closing = _close(clean, opening, '{', '}')
        if closing is None:
            continue
        block = clean[opening + 1:closing]
        loop = re.search(r'\bdo\s*\{', block)
        if not loop:
            continue
        body_open = opening + 1 + loop.end() - 1
        body_close = _close(clean, body_open, '{', '}')
        tail = re.compile(r'\s*while\s*\(').match(clean, body_close + 1) if body_close else None
        if not tail:
            continue
        cond_open = tail.end() - 1
        cond_close = _close(clean, cond_open, '(', ')')
        cond = clean[cond_open:cond_close + 1]
        read = re.search(rf'(?<![\w.>]){base}\s*\[\s*{index}\s*\]', cond)
        if re.search(r'\blim\b', block):
            continue
        if not read or _assigned(clean[opening:closing], index) or _assigned(clean[opening:closing], base):
            continue
        kind = _element_type(header + '\n' + source, clean, base)
        if not kind:
            continue
        indent = re.match(r'[ \t]*', clean[clean.find('\n', opening) + 1:]).group(0)
        first = clean.find('\n', opening) + 1
        sites.append([(first, first, f'{indent}{kind} *lim = {base} + {index};\n'),
                      (cond_open + read.start(), cond_open + read.end(), '*lim')])
    out = []
    for site in sites[:LIMIT]:
        out.append((FAMILY, edit(source, site)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
