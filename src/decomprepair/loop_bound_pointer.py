"""A loop bounded by a global, written to read the global through a volatile pointer set in the loop's own test.

The bound of a counted loop that is also read in its body (`for (i = 0; i < gCount; i++) { switch (gCount) ... }`) is
a plain global in every draft, and every read is `lui` + `lw %lo`. A matched neighbour of the same overlay wrote the
count as `volatile s32 *count = &gVisibleSaveSlotCount;` and read `*count`, so the target keeps the global's address in
a register (`lui $a1; addiu $a1, $a1, %lo(count); lw $v0, ($a1)`) across the first test, the loop head's reads and the
loop's own test, and loads it again after the calls. cse folds a pointer set before the loop back into the constant
(measured: the same instructions as the plain global, 9321 either way); a volatile pointer assigned inside the loop's test,
`i < *(p = &gCount)`, is copied with the test to the loop's two ends and the body's reads of `*p` keep the register
(9321 -> 9151 on a 534-instruction panel builder, the three rows of the address loads and the loop end exact).
Why only the volatile pointer survives is a hypothesis (cse's folding of a constant-valued pointer into the volatile
reference is not what the target shows), measured on one function.

`variants` reads each `for (...; i < G; ...) { ... }` whose bound `G` is an `extern` scalar of the file (`extern s32 G;`),
which the loop's body does not assign or take the address of, and writes `volatile T *loop_bound_ptr;` at the top of the
function, the bound as `*(loop_bound_ptr = &G)` and the body's other reads of `G` as `*loop_bound_ptr`. Two children:
with the body's reads rewritten and with only the test."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_bound_pointer'
FAMILIES = (FAMILY,)
POINTER = 'loop_bound_ptr'
IDENT = r'[A-Za-z_]\w*'
SCALAR = r'(?:(?:unsigned|signed)\s+)?(?:int|long|short|char)|[su](?:8|16|32)'
FOR = re.compile(r'\bfor\s*\(([^;{}()]*);([^;{}()]*);([^;{}()]*)\)\s*\{')
BOUND = re.compile(rf'^\s*({IDENT})\s*(<=|<)\s*({IDENT})\s*$')


def variants(source, name):
    span = find(source, name)
    if not span or POINTER in source:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    out = []
    for loop in FOR.finditer(clean, opening, span[1]):
        test = BOUND.match(loop[2])
        if not test:
            continue
        bound = test[3]
        declared = re.search(rf'(?m)^[ \t]*extern\s+((?:volatile\s+)?)({SCALAR})\s+{re.escape(bound)}\s*;', clean[:span[0]])
        if not declared or declared[1]:
            continue  # not a plain extern scalar of the file
        body_open = loop.end() - 1
        body_close = close(clean, body_open, '{', '}')
        if not body_close:
            continue
        body = clean[body_open:body_close]
        if re.search(rf'(?<![\w.]){re.escape(bound)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|&\s*{re.escape(bound)}\b|(?:\+\+|--)\s*{re.escape(bound)}\b|\b{re.escape(bound)}\s*(?:\+\+|--)', body):
            continue
        decl = f'    volatile {declared[2]} *{POINTER};\n'
        cond_at = loop.start(2) + loop[2].index(bound)
        for rewrite_body in (True, False):
            text = source[:cond_at] + f'*({POINTER} = &{bound})' + source[cond_at + len(bound):loop.end()]
            inner = source[loop.end():body_close]
            if rewrite_body:
                inner = re.sub(rf'(?<![\w.]){re.escape(bound)}\b', f'*{POINTER}', inner)
                if inner == source[loop.end():body_close]:
                    continue
            text += inner + source[body_close:]
            line = source.find('\n', opening) + 1
            text = text[:line] + decl + text[line:]
            out.append(text)
        break
    return [(FAMILY, text) for text in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 65}
