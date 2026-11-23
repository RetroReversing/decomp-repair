"""A default value set before an `if` that sets it, written in the `if`'s `else` arm, and the other way round.

m2c writes `x = 0; if (c) { x = f(); }` where a compiler's output may have come from `if (c) { x = f(); } else { x =
0; }`, and the two compile differently: the default before the test is one insn that the scheduler can fill a branch's
delay slot with, and an `else` arm is a block of its own that jump threading, cross-jumping and delay-slot filling
treat differently. In a KMC GCC 2.7.2 function the last of three clamps in an `if`'s arm ended in `bnel $v0,$zero,L;
lui $a3,0x7F; j L2; move $a0,$s6; L: move $a0,$s6` in the target and fell straight through in the draft: the `j` over
an `else` block whose only insn the delay slot of the first test had taken. The default written as `else { a3 = 0; }`
(and the same for a second default two tests earlier) made the function exact; each alone left it at 335 / 400.

A default that is a small expression with no call (`len = n * 4;` before `if (n > 0x100) { len = 0x400; }`, a KMC or IDO
loop-bound clamp: `if (n > 0x100) { len = 0x400; } else { len = n * 4; }` is the branch layout of the target, the
default before the test is not) takes the same moves as `default_expression_into_else` and `default_expression_into_then`,
when the test has no call either and the arm sets the local on a line of its own outer level.

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
EXPRESSION = 'default_expression_into_else'
EXPRESSION_THEN = 'default_expression_into_then'
FAMILIES = (FAMILY, INVERSE, THEN, EXPRESSION, EXPRESSION_THEN)
_DEFAULT = re.compile(r'(?P<x>[A-Za-z_]\w*) = (?P<d>-?(?:0[xX][0-9A-Fa-f]+|\d+)|[A-Za-z_]\w*);')
# a default that is a small side-effect-free expression (`len = n * 4;`): no call, no assignment, no `++`/`--`
_EXPRESSION = re.compile(r'(?P<x>[A-Za-z_]\w*) = (?P<d>[^;={}]*[^;={}\s]);')
_EFFECT = re.compile(r'[A-Za-z_]\w*\s*\(|\+\+|--|\bvolatile\b|[+\-*/%&|^]=|<<=|>>=')


def _test_after(body, i):
    """The index of the `if (` line the default at `i` leads into: the next line, or the next after the `}` that closes
    the bare block the default ends (a block of statements that always runs: `{ ...; x = 0; } if (c) { x = f(); }`)."""
    if i + 1 >= len(body):
        return None
    if body[i + 1].stripped.startswith('if (') and i + 2 < len(body):
        return i + 1
    if body[i + 1].stripped == '}' and i + 2 < len(body) and body[i + 2].stripped.startswith('if ('):
        first = block_start(body, i + 1)
        before = body[first - 1].stripped if first else ''
        if first and body[first].stripped == '{' and before.endswith((';', '{', '}')):
            return i + 2
    return None


def _top_level_set(inside, x):
    """True when the arm assigns `x` on a line of its own outer level, so that no path through it leaves the default."""
    if not inside:
        return False
    level = inside[0].indent
    return any(l.indent == level and re.match(rf'{re.escape(x)} =(?!=)', l.stripped) for l in inside)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = []
    for i, line in enumerate(body):
        hit = _DEFAULT.fullmatch(line.stripped)
        expression = None
        if not hit:
            expression = _EXPRESSION.fullmatch(line.stripped)
            if expression and (_EFFECT.search(expression['d']) or mentions(expression['d'], expression['x'])
                               or _DEFAULT.fullmatch(line.stripped)):
                expression = None
            hit = expression
        j = _test_after(body, i) if hit else None
        if hit and j and not body[j].stripped.endswith(';'):
            opening = block_open(body, j)
            closing = block_end(body, opening) if opening is not None else None
            if closing is None or (closing + 1 < len(body) and body[closing + 1].stripped.startswith('else')):
                continue
            inside = '\n'.join(l.text for l in body[opening + 1:closing])
            if mentions(body[j].text, hit['x']) or not re.search(rf'(?m)^\s*{re.escape(hit["x"])} =(?!=)', inside) \
                    or reads_first(inside, hit['x']):
                continue
            if expression and (_EFFECT.search(re.sub(r'^\s*if\b', '', body[j].text)) or not _top_level_set(body[opening + 1:closing], hit['x'])):
                continue
            indent = body[j].indent
            arm = f'{indent}else\n{indent}{{\n{indent}  {line.stripped}\n{indent}}}\n'
            out.append((EXPRESSION if expression else FAMILY,
                        apply(source, [(line.start, line.end, ''), (body[closing].end, body[closing].end, arm)])))
            test = re.fullmatch(r'if \((.*)\)', body[j].stripped)
            inverse = negate(test[1]) if test else None
            if inverse:
                text = ''.join(l.source + '\n' for l in body[opening + 1:closing])
                whole = (f'{indent}if ({inverse})\n{indent}{{\n{indent}  {line.stripped}\n{indent}}}\n'
                         f'{indent}else\n{indent}{{\n{text}{indent}}}\n')
                out.append((EXPRESSION_THEN if expression else THEN,
                            apply(source, [(line.start, line.end, ''), (body[j].start, body[closing].end, whole)])))
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
