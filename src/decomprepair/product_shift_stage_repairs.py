"""A shifted value feeding a product, computed first in a `do { } while (0)` of its own.

`d = a - (b * (t >> 8));` expands the shift next to the multiply, and the scheduler orders the product's operand
loads before the shift. The register allocator then gives the first-born value of the pair the lowest register, and
the shift result (which the target computed first, in the delay slot of the test before it) lands in `$v0` where the
game's is `$v1`, mirroring a whole chain of five rows. The loop notes a `do { } while (0)` leaves are scheduling
boundaries and nothing else survives into the object, so staging the shift in a scope of its own (`do { s = t >> 8;
} while (0);` and `b * s`) fixes the order. Measured on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3
-mgp32 -mfp32 -O2`): 435 -> 400, the five rows of the chain gone. Each shift that is one operand of a product in an
assignment gets one variant. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, lines, with_local

FAMILY = 'product_shift_stage'
FAMILIES = (FAMILY,)
_SHIFT = re.compile(r'\((?P<v>[A-Za-z_]\w*) >> (?P<n>\d+)\)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for line in body:
        text = line.stripped
        if not re.match(r'[A-Za-z_]\w* = ', text) or not text.endswith(';'):
            continue
        for hit in _SHIFT.finditer(text):
            if not re.search(r'\*\s*$', text[:hit.start()]) and not re.match(r'\s*\*', text[hit.end():]):
                continue
            local = 'shift_stage'
            if re.search(rf'\b{local}\b', part.clean):
                continue
            declaration = with_local(source, part, f's32 {local};')
            if not declaration:
                continue
            indent = line.indent
            scope = (f'{indent}do\n{indent}{{\n{indent}  {local} = {hit["v"]} >> {hit["n"]};\n{indent}}}\n'
                     f'{indent}while (0);\n')
            replaced = line.source[:line.source.index(hit[0])] + local + line.source[line.source.index(hit[0]) + len(hit[0]):]
            out.append((FAMILY, apply(source, [declaration, (line.start, line.start, scope),
                                               (line.start, line.start + len(line.source), replaced)])))
            break
    return out
