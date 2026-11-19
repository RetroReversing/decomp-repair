"""A result variable that only ever holds constants, returned where each is set.

m2c merges a function's returns into one variable: `v = 0; if (f() == 0x21) { if (g() == 5) { v = 1; } } return
v;`. gcc then keeps the 0 in a register across both calls. An N64 function was 64.3% so (with a `register v = 0;`
a rewrite left behind) and exact as `if (...) { if (...) { return 1; } } return 0;`. Offered only when every
assignment of the variable is a constant followed by nothing but closing braces before the final `return v;`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'flag_returns'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    tail = re.search(r'\breturn\s+(' + IDENT + r')\s*;\s*\}\s*$', clean[opening:end])
    if not tail:
        return []
    var = tail[1]
    returned_at = opening + tail.start()
    body = clean[opening:end]
    uses = [m for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)]
    assigns = list(re.finditer(r'(?m)^([ \t]*)(?:register\s+)?' + var + r'\s*=\s*(' + NUMBER + r')\s*;[ \t]*\n', body))
    declared = re.search(r'(?m)^[ \t]*(?:register\s+)?[\w ]+?\s+' + var + r'\s*;[ \t]*\n', body)
    if not assigns or not declared or len(uses) != len(assigns) + 2:
        return []
    # the first assignment, at the function's own level before anything else uses it, is the default
    first = assigns[0]
    edits = [(opening + declared.start(), opening + declared.end(), ''), (opening + first.start(), opening + first.end(), '')]
    default = first[2]
    for m in assigns[1:]:
        if re.search(r'(?m)^[ \t]*register\s', clean[opening + m.start():opening + m.end()]):
            if m[2] != default:
                return []
            edits.append((opening + m.start(), opening + m.end(), ''))  # a leftover shadowing declaration
            continue
        after = clean[opening + m.end():returned_at]
        if re.sub(r'[\s}]', '', after):
            return []  # something runs between the assignment and the return: it can't return there
        edits.append((opening + m.start(), opening + m.end(), f'{m[1]}return {m[2]};\n'))
    edits.append((returned_at, clean.find(';', returned_at) + 1, f'return {default};'))
    text = source
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    return [(FAMILY, text)] if text != source else []
