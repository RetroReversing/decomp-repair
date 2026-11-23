"""An outer one-shot scope removed and one long statement given a scope of its own, as one child (GCC 2.7.2, KMC, N64).

A saved best searched from m2c's goto-ladder often wraps whole loop nests in `do { ... } while (0);` (a loop-depth
weight: flow.c adds the loop depth to every reference it counts, and local-alloc.c and global.c rank pseudo registers
by `floor_log2 (refs) * refs / live length`). The wrapper raises every reference in the nest by one, which was right
for one statement and wrong for another: in a 529-instruction function the plane distance of a float chain (a sum of
four products read from two records) needed the extra depth, while two compares further down the same loop body needed
one less (at depth 4 a pair `a - b` and its compare ranked the second load first, at depth 3 the sum took the register
the target gave it; `local-alloc.c` ties the sum to its first operand, and which of two quantities goes first flips at
the depth where `floor_log2 (4 * d) * 4 * d / 3` and `floor_log2 (2 * d) * 2 * d` cross). Taking the wrapper off moves
the compares to the target and the chain away from it; only taking it off and wrapping the chain (its store and its
guard with it) gives both: 500 -> 460 on that function, where each half alone was 505 and 970.

This family offers that pair: for each wrapper `do { } while (0);` that holds a loop and no `break`/`continue`/`case`,
the wrapper removed and, for each statement of its body that is a long chain of loads (six or more `*((T *)` reads in
one assignment), the statement wrapped alone, or with the `if` block that follows it (the early-out the chain
decides). A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view
from .line_scan import lines
from .pattern_repairs import close

FAMILY = 'scope_unwrap_rewrap'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 24
LOADS = 6
_DO = re.compile(r'\bdo\s*\{')
_LOOP = re.compile(r'\b(?:while|for)\s*\((?!\s*0\s*\))')
_JUMPS = re.compile(r'\b(?:break|continue|case|default)\b')
_CHAIN = re.compile(r'^[A-Za-z_]\w*\s*=\s*[^;]*;')


def _wrappers(clean, part):
    """(start of `do`, past `{`, the `}`, end of `while (0);`) of each one-shot wrapper that holds a loop."""
    found = []
    for hit in _DO.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1, '{', '}')
        tail = re.match(r'\s*while\s*\(\s*0\s*\)\s*;', clean[shut:]) if shut else None
        if not tail:
            continue
        inner = clean[hit.end():shut - 1]
        if not _LOOP.search(inner) or _JUMPS.search(inner):
            continue
        found.append((hit.start(), hit.end(), shut - 1, shut + tail.end()))
    return found


def _spans(clean, source, part, lo, hi):
    """Each long load chain between `lo` and `hi`: the line alone, and the line with the `if` block after it."""
    spans = []
    for line in lines(part, source):
        if line.start < lo or line.end > hi:
            continue
        text = line.stripped
        if not _CHAIN.match(text) or len(re.findall(r'\*\(\(', text)) < LOADS:
            continue
        spans.append((line.start, line.end))
        after = re.match(r'\s*if\s*\(', clean[line.end:])
        if after:
            paren = close(clean, line.end + after.end() - 1)
            block = re.match(r'\s*\{', clean[paren:]) if paren else None
            end = close(clean, paren + block.end() - 1, '{', '}') if block else None
            if end and end <= hi:
                spans.append((line.start, source.find('\n', end) + 1 or end))
    return spans


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for start, body, shut, end in _wrappers(clean, part):
        removal = [(start, body, ''), (shut, end, '')]
        for lo, hi in _spans(clean, source, part, body, shut):
            indent = re.match(r'[ \t]*', source[lo:])[0]
            wrapped = [(lo, lo, f'{indent}do\n{indent}{{\n'), (hi, hi, f'{indent}}}\n{indent}while (0);\n')]
            text = edit(source, removal + wrapped)
            if text != source:
                out.append((FAMILY, text))
            if len(out) >= MAX_CHILDREN:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
