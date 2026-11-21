"""A `while` loop whose first load is one its own test already made, with a label to stop cse sharing it.

gcc 2.7.2 writes `while (A) { m = P; ... }` as a copy of the test before the loop, the body, and the test again at the
bottom (jump.c's loop exit test duplication). When the body's first statement loads what the test reads (`m = n->head;`
beside `while (n->head->key != -1)`), cse follows the fall-through from the copied test into the loop's top label, sees
the same address already in a register and drops the load: `m` is then carried round the loop with a copy at the
bottom (`move $a1,$a0`). A target that reloads `m` at the top, and whose delay slots and hoisted constants all follow,
was reached from the same C once the body's first statement carried a label: a named label is kept by the jump
optimiser and ends the extended basic block there, so cse reloads. An MIPS function that stood at 505 on a block of
rows was at 230 with `top: m = ...;`: its remaining rows were registers, and the loop, the hoisted `li $s0,-1`
(the `nop` delay slot after the first `beq`) and the reload were the target's.

Only a `while` loop (a `do`/`while` has no test copy to share with), a first body statement `x = LOAD;` whose right
side is also a sub-expression of the test, and no label already there.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_top_label'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
FIRST = re.compile(r'\s*(?P<lhs>' + IDENT + r')\s*=(?!=)\s*(?P<rhs>[^;{}]+);')
LABELLED = re.compile(r'\s*' + IDENT + r'\s*:(?!:)')


def _norm(text):
    return re.sub(r'\s+', '', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for loop in re.finditer(r'\bwhile\s*\(', clean[opening:end]):
        at = opening + loop.start()
        paren = at + loop.group().rindex('(')
        after = close(clean, paren)
        if not after:
            continue
        rest = clean[after:end]
        brace = re.match(r'\s*\{', rest)
        if not brace:  # `do { } while (c);`, or a body without braces
            continue
        body = after + brace.end()
        first = FIRST.match(clean, body)
        if not first or LABELLED.match(clean, body):
            continue
        rhs = _norm(first['rhs'])
        # a load (a dereference, a subscript or a field), never a plain copy or arithmetic on locals
        if not re.search(r'\*|\[|->', rhs) or rhs not in _norm(clean[paren + 1:after - 1]):
            continue
        label = f'__repair_loop_top_{len(result)}'
        start = body + len(first.group()) - len(first.group().lstrip())
        result.append((FAMILY, f'{source[:start]}{label}: {source[start:]}'))
    return result
