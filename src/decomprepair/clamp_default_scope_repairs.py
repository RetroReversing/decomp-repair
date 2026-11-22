"""A clamp's default value written in a `do { } while (0)`, so its branch keeps the arm that carries the other value.

m2c writes a clamp as `if (x >= 0) { v = 0x7F0000; if (x <= 0x7F0000) { v = x; } } else { v = 0; }`. GCC's jump pass
folds that into `bnez c,L; lui v; L:` with the copy `move v,x` placed after, where the target kept both arms as
`bnez $v0,L; lui $a0,0x7F (delay slot); j L2; move $a0,$v1 (delay slot)`: the branch skips the copy, and the `j`
carries it. Written `do { v = 0x7F0000; } while (0);`, the loop notes around the default stop the fold. Measured on a
719-instruction N64 function with two such clamps (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): 4080 -> 3620 and
3655 -> 3255. Offered for an assignment of a number to a local directly followed by an `if` whose body assigns the same
local. The plain `if (x > M) x = M;` clamp gains nothing from it. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, lines

FAMILY = 'clamp_default_scope'
FAMILIES = (FAMILY,)
_DEFAULT = re.compile(r'(?P<v>[A-Za-z_]\w*) = (?:0[xX][0-9A-Fa-f]+|\d+);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body[:-3]):
        hit = _DEFAULT.fullmatch(line.stripped)
        if not hit or not body[i + 1].stripped.startswith('if (') or body[i + 2].stripped != '{':
            continue
        closing = block_end(body, i + 2)
        if closing is None or not re.fullmatch(rf'{hit["v"]} = [^;]*;', body[i + 3].stripped):
            continue
        indent = line.indent
        scope = f'{indent}do\n{indent}{{\n{indent}  {line.stripped}\n{indent}}}\n{indent}while (0);\n'
        out.append((FAMILY, apply(source, [(line.start, line.end, scope)])))
    return out
