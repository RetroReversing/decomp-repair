"""m2c's range test and empty arm for a `switch` whose low cases share one body, written back as the `switch`.

A `switch` on an unsigned value with cases 0..K-1 sharing a body and case K another becomes a range test and a compare,
which m2c reads back as

    if (x >= 4U) {
        if (x != 4) {

        } else {
            B;
        }
    } else {
        A;
    }

An N64 function was 95.4% so, 93.2% as `if (x < 4U) A; else if (x == 4) B;`, and exact as `switch (x) { case 0: case 1:
case 2: case 3: A; break; case 4: B; break; }`. Offered for K up to 8.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'range_case_switch'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
SHAPE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<x>' + IDENT + r')\s*>=\s*(?P<k>\d+)[uU]\s*\)\s*\{\s*\n'
    r'[ \t]*if\s*\(\s*(?P=x)\s*!=\s*(?P=k)[uU]?\s*\)\s*\{\s*\}\s*else\s*\{(?P<b>[^{}]*)\}\s*\n'
    r'[ \t]*\}\s*else\s*\{(?P<a>[^{}]*)\}[ \t]*\n')


def _body(text, indent):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return ''.join(f'{indent}    {line}\n' for line in lines) + f'{indent}    break;\n'


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
    for hit in SHAPE.finditer(clean, opening, end):
        k = int(hit['k'])
        if not 1 <= k <= 8:
            continue
        indent = hit['indent']
        a = source[hit.start('a'):hit.end('a')]
        b = source[hit.start('b'):hit.end('b')]
        low = ' '.join(f'case {i}:' for i in range(k))
        text = (f'{indent}switch ({hit["x"]}) {{\n{indent}{low}\n{_body(a, indent)}'
                f'{indent}case {k}:\n{_body(b, indent)}{indent}}}\n')
        result.append((FAMILY, source[:hit.start()] + text + source[hit.end():]))
    return result
