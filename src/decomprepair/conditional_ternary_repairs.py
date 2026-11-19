"""`v = a; if (c) { v = b; } return v;` written as the conditional expression it came from.

gcc 2.7.2 builds a `?:` with the branch around a single instruction in the delay slot, and m2c's variable and `if`
with a likely branch over it. An N64 `abs` was 60% as m2c wrote it and exact as `return (x >= 0) ? x : -x;`. Offered
with the test as written and inverted, for a variable set once before a one-statement `if` and then returned.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'conditional_ternary'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    shape = re.compile(r'(?m)^(?P<ind>[ \t]*)(?P<v>' + I + r')\s*=\s*(?P<a>[^;\n]+);[ \t]*\n'
                       r'[ \t]*if \((?P<c>[^\n]*)\) \{[ \t]*\n[ \t]*(?P=v)\s*=\s*(?P<b>[^;\n]+);[ \t]*\n[ \t]*\}[ \t]*\n'
                       r'[ \t]*(?:return (?P=v)|(?P<lv>' + I + r')\s*=(?!=)\s*(?P=v));')
    result = []
    for hit in shape.finditer(clean, opening, end):
        v, a = hit['v'], source[hit.start('a'):hit.end('a')].strip()
        if re.search(r'\b' + I + r'\s*\(|\+\+|--', a) or re.search(r'\b' + v + r'\b', a):
            continue
        b = re.sub(r'\b' + v + r'\b', a, source[hit.start('b'):hit.end('b')].strip())
        c = source[hit.start('c'):hit.end('c')].strip()
        if re.search(r'\b' + v + r'\b', c):
            c = re.sub(r'\b' + v + r'\b', a, c)
        ind = hit['ind']
        # (a store of the value, `D = v;`, as well as its return: an N64 library's error wrapper stored the result
        # code to a global, 99.4% carried in a variable and exact as the conditional expression)
        lead = 'return ' if hit['lv'] is None else hit['lv'] + ' = '
        if hit['lv'] is not None and re.search(r'\b' + v + r'\b', clean[hit.end():end]):
            continue
        forms = []
        inverse = negate(c)
        if inverse:
            forms.append(f'{ind}{lead}({inverse}) ? {a} : {b};')
        forms.append(f'{ind}{lead}({c}) ? {b} : {a};')
        for form in forms:
            text = source[:hit.start()] + form + source[hit.end():]
            decl = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + v + r'\s*;[ \t]*\n', text[opening:])
            if decl and len(re.findall(r'\b' + v + r'\b', _blank(text)[opening:])) == 1:
                text = text[:opening + decl.start()] + text[opening + decl.end():]
            result.append((FAMILY, text))
    return result[:2]
