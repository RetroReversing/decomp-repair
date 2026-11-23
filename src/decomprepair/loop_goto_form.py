"""A `do { } while (c);` loop written as a backward `goto`, so GCC 2.x's loop pass leaves its invariants where they are.

`goto_loop_invariants` goes the other way: m2c's `again: ... if (c) goto again;` as the loop it was. Here the target is the
case where the game's loop was not one to loop.c (a `for` whose test was written with a `continue`, a loop another pass
rewrote), so its float literals (`lui $at; ori $at; mtc1`) and a double global's address stay inside the body, where the
`do { } while` draft has them hoisted into callee-saved registers before the loop:

    do {                                  loop_top:
        a = f(x);                           {
        x += 0.21f;              ->             a = f(x);   x += 0.21f;  ...
    } while (i < 64);                       }
                                            if (i < 64) goto loop_top;

The registers the hoisted literals took are free again: a 64-step sine table loop (two `sinApprox` calls and one
`__cosf`, three float literals, a double global's second word and the tail of the table address) of a 1133-instruction
effect spawner, KMC GCC 2.7.2: 4035 -> 3555 for this edit alone. Offered, one child per loop, for the `do` loops whose
body has a call and a float literal (the loops the pass hoists out of while a call is in them), not for a body that
`break`s, `continue`s, `return`s, has a `switch` or declares its own locals (a `goto` into a block's scope would skip
their initialisers).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_goto_form'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'
UNSAFE = re.compile(r'\b(?:break|continue|return|switch|case|default|goto|volatile|asm|__asm__)\b')
CALL = re.compile(r'(?<![\w)])(?!(?:if|while|for|switch|return|sizeof)\b)' + IDENT + r'\s*\(')
FLOAT_LITERAL = re.compile(r'(?<![\w.])\d+\.\d*f\b|(?<![\w.])\.\d+f\b')
DECLARATION = re.compile(r'(?m)^\s*(?:unsigned\s+\w+|signed\s+\w+|[su](?:8|16|32)|f32|f64|int|short|char|float|double|void\s*\*+|\w+\s*\*+)\s+' + IDENT + r'\s*(?:=[^;]*)?;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    result = []
    for hit in re.finditer(r'(?m)^([ \t]*)do[ \t]*\n?[ \t]*\{', clean[opening:end]):
        body_open = opening + hit.end() - 1
        body_close = close(clean, body_open, '{', '}')
        if not body_close:
            continue
        tail = re.match(r'\s*while\s*\(([^;{}]*)\)\s*;', clean[body_close:end])
        if not tail:
            continue
        body = clean[body_open + 1:body_close - 1]
        if UNSAFE.search(body) or not CALL.search(body) or not FLOAT_LITERAL.search(body) or DECLARATION.search(body):
            continue
        label = 'loop_top'
        if re.search(r'\b' + label + r'\b', source):
            label = f'loop_top_{len(result) + 1}'
            if re.search(r'\b' + label + r'\b', source):
                continue
        start = opening + hit.start()
        indent = hit[1]
        text = (f'{indent}{label}:\n{indent}' + source[body_open:body_close] + f'\n{indent}if ({source[body_close + tail.start(1):body_close + tail.end(1)]}) goto {label};')
        result.append((FAMILY, source[:start] + text + source[body_close + tail.end():]))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
