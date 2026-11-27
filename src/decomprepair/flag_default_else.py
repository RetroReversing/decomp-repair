"""A flag cleared before a guarded block that sets it last, written as the guard's `else` arm.

    done = 0;                              if (a != 1.0 && b != 1.0) {
    if (a != 1.0 && b != 1.0) {                scale(m, a, b);
        scale(m, a, b);              ->        done = 1;
        done = 1;                          } else {
    }                                          done = 0;
                                           }

Both compile to the clear in the guard branch's delay slot, but the flag lives from another place, which moves its
allocation priority: an N64 object renderer (KMC GCC 2.7.2 `-O1`, 258 instructions) had the flag and a shifted index
in each other's saved registers (330) and matched with the `else` arm. `const_arm_conditional_set` covers a guarded
body that is the one assignment; here the body does other work first.

Children (`flag_default_else`): each `V = K;` followed by `if (C) { ...; V = K2; }` with no `else`, where `V` is a
local, `C` does not read it and the body names it only in that last assignment.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'flag_default_else'
FAMILIES = (FAMILY,)
LIMIT = 8
LITERAL = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
CLEARED = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<v>[A-Za-z_]\w*) = (?P<k>{LITERAL});\n[ \t]*if \(')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    result = []
    for found in CLEARED.finditer(clean, opening, span[1]):
        flag = found['v']
        declared = re.search(rf'(?m)^[ \t]*(?:unsigned |signed )?[A-Za-z_]\w*[ \t]+{flag};', clean[opening:span[1]])
        paren = found.end() - 1
        end_condition = close(clean, paren, '(', ')')
        if not declared or end_condition is None or re.search(rf'\b{flag}\b', clean[paren:end_condition]):
            continue
        brace = clean.find('{', end_condition)
        if brace < 0 or clean[end_condition:brace].strip():
            continue
        end = close(clean, brace, '{', '}')
        if end is None or re.match(r'\s*else\b', clean[end:]):
            continue
        body = clean[brace + 1:end - 1]
        last = re.search(rf'(?<![\w.>]){flag} = {LITERAL};\s*\Z', body)
        # named once in the body, by that last statement of the block itself
        if not last or len(re.findall(rf'\b{flag}\b', body)) != 1:
            continue
        before = body[:last.start()].rstrip()
        # the block's own statement, not a nested block's or the arm of an unbraced `if`
        if before.count('{') != before.count('}') or before and not before.endswith((';', '}')):
            continue
        indent = found['indent']
        text = (source[:found.start()] + indent + source[found.start() + len(found[0]) - len('if ('):end]
                + f' else {{\n{indent}    {flag} = {source[found.start("k"):found.end("k")]};\n{indent}}}'
                + source[end:])
        result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
