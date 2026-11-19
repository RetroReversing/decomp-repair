"""m2c's temporary assigned inside a condition with a comma, written where it's used.

m2c keeps a value the game computed twice (once in a test, once after it) as one temporary assigned by a comma inside
the condition:

    if ((i >= 0x10U) || (temp_v1 = i * 0x18, (*(&D_80107B68 + temp_v1) == 0))) {
        return g(0x3004);
    }
    return temp_v1 + &D_80107B6A;

gcc then keeps `temp_v1` in a register across the branch, where the game recomputed it. Written at each use, as
`(*(&D_80107B68 + i * 0x18) == 0)` and `return i * 0x18 + &D_80107B6A;`, an N64 function went from 75% to 90.9%, and
two existing families after it (m2c_refinement, table_read_width) made it exact. Offered only when the temporary is a
plain local assigned nowhere else, its value has no call or side effect, and nothing it reads is assigned after it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'comma_temporary_inline'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def _assigned(name, text):
    return re.search(r'(?<![\w.>])' + re.escape(name) + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*'
                     + re.escape(name) + r'\b|\b' + re.escape(name) + r'\s*(?:\+\+|--)', text)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    declared = set(re.findall(r'(?m)^[ \t]*[\w ]+?[\s*]+(' + IDENT + r')\s*;', body))
    result = []
    for hit in re.finditer(r'\(\s*(?P<var>' + IDENT + r')\s*=(?!=)\s*', clean[opening:end]):
        var = hit['var']
        if var not in declared:
            continue
        group_open = opening + hit.start()
        group_close = close(clean, group_open)
        if not group_close:
            continue
        # the value runs to the group's top-level comma
        depth, comma = 0, None
        for i in range(opening + hit.end(), group_close - 1):
            ch = clean[i]
            depth += (ch in '([') - (ch in ')]')
            if depth == 0 and ch == ',':
                comma = i
                break
            if depth < 0:
                break
        if comma is None:
            continue
        value = source[opening + hit.end():comma].strip()
        if re.search(IDENT + r'\s*\(', value) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', value):
            continue
        rest = clean[comma + 1:end]
        before = clean[opening:group_open]
        if _assigned(var, before + rest) or re.search(r'(?<![\w.>])' + re.escape(var) + r'\b',
                                                      re.sub(r'(?m)^[ \t]*[\w ]+?[\s*]+' + re.escape(var) + r'\s*;', '', before)):
            continue
        names = set(re.findall(r'(?<![\w.])' + IDENT, re.sub(r'\b0[xX][0-9a-fA-F]+\b', '', value)))
        if any(_assigned(n, rest) for n in names):
            continue
        tail = re.sub(r'(?<![\w.>])' + re.escape(var) + r'\b', '(' + value + ')', source[comma + 1:end].lstrip())
        text = source[:group_open + 1] + tail + source[end:]
        declaration = re.compile(r'(?m)^[ \t]*[\w ]+?[\s*]+' + re.escape(var) + r'\s*;[ \t]*\n')
        if not re.search(r'(?<![\w.>])' + re.escape(var) + r'\b', declaration.sub('', _blank(text))):
            text = declaration.sub('', text, count=1)
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result[:4]
