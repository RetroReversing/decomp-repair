"""A default value set before an `if` that sets it, written in the `if`'s `else` arm, and the other way round.

m2c writes `x = 0; if (c) { x = f(); }` where a compiler's output may have come from `if (c) { x = f(); } else { x =
0; }`, and the two compile differently: the default before the test is one insn that the scheduler can fill a branch's
delay slot with, and an `else` arm is a block of its own that jump threading, cross-jumping and delay-slot filling
treat differently. In a KMC GCC 2.7.2 function the last of three clamps in an `if`'s arm ended in `bnel $v0,$zero,L;
lui $a3,0x7F; j L2; move $a0,$s6; L: move $a0,$s6` in the target and fell straight through in the draft: the `j` over
an `else` block whose only insn the delay slot of the first test had taken. The default written as `else { a3 = 0; }`
(and the same for a second default two tests earlier) made the function exact; each alone left it at 335 / 400.

Both directions: the default of a local moved into an `else` that the `if` doesn't have yet (the body must assign the
local before reading it), and a lone `else { x = default; }` moved up in front of its `if`.

`default_into_then` is the same move with the test inverted, so the default is the then arm and the body the `else`:
`x = 0xA0; if (c != 0xFF) { x = y; }` -> `if (c == 0xFF) { x = 0xA0; } else { x = y; }`. The two arm orders lay the
branch out differently (which block is out of line): in a KMC GCC 2.7.2 N64 function a halfword's value read from an
`if (m != 0xFF)` guard went 95 -> 80 written with the default as the then arm, and 15 -> 0 once the rest of the function
was in place (the arm order of `default_into_else` alone changed nothing).
"""
import re

from .integer_repair_support import view
from .line_scan import apply, block_end, block_open, block_start, lines, mentions, reads_first
from .pattern_repairs import negate

FAMILY = 'default_into_else'
INVERSE = 'else_into_default'
THEN = 'default_into_then'
FAMILIES = (FAMILY, INVERSE, THEN)
_DEFAULT = re.compile(r'(?P<x>[A-Za-z_]\w*) = (?P<d>-?(?:0[xX][0-9A-Fa-f]+|\d+)|[A-Za-z_]\w*);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body):
        hit = _DEFAULT.fullmatch(line.stripped)
        if hit and i + 2 < len(body) and body[i + 1].stripped.startswith('if (') and not body[i + 1].stripped.endswith(';'):
            opening = block_open(body, i + 1)
            closing = block_end(body, opening) if opening is not None else None
            if closing is None or (closing + 1 < len(body) and body[closing + 1].stripped.startswith('else')):
                continue
            inside = '\n'.join(l.text for l in body[opening + 1:closing])
            if mentions(body[i + 1].text, hit['x']) or not re.search(rf'(?m)^\s*{re.escape(hit["x"])} =(?!=)', inside) \
                    or reads_first(inside, hit['x']):
                continue
            indent = body[i + 1].indent
            arm = f'{indent}else\n{indent}{{\n{indent}  {line.stripped}\n{indent}}}\n'
            out.append((FAMILY, apply(source, [(line.start, line.end, ''), (body[closing].end, body[closing].end, arm)])))
            test = re.fullmatch(r'if \((.*)\)', body[i + 1].stripped)
            inverse = negate(test[1]) if test else None
            if inverse:
                text = ''.join(l.source + '\n' for l in body[opening + 1:closing])
                whole = (f'{indent}if ({inverse})\n{indent}{{\n{indent}  {line.stripped}\n{indent}}}\n'
                         f'{indent}else\n{indent}{{\n{text}{indent}}}\n')
                out.append((THEN, apply(source, [(line.start, line.end, ''), (body[i + 1].start, body[closing].end, whole)])))
        if line.stripped == 'else':
            opening = block_open(body, i)
            closing = block_end(body, opening) if opening is not None else None
            if closing is None or closing - opening != 2 or not _DEFAULT.fullmatch(body[opening + 1].stripped):
                continue
            if i == 0 or body[i - 1].stripped != '}':
                continue
            first = block_start(body, i - 1)
            ifs = first - 1 if first else -1
            if ifs < 0 or not body[ifs].stripped.startswith('if ('):
                continue
            moved = body[ifs].indent + body[opening + 1].stripped + '\n'
            out.append((INVERSE, apply(source, [(body[i].start, body[closing].end, ''), (body[ifs].start, body[ifs].start, moved)])))
    return out
