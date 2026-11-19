"""Loop and conversion shapes m2c expands that the deep pass couldn't climb back from.

`do_constant_body`: a polling loop whose only body m2c filled with the next loop's counter start,

    do {
        var_s0 = 0;
    } while (osRecvMesg(&D, 0, 0) == 0);

is the empty `while` the game wrote, the counter set after it: an N64 function (11 instructions) went from 86% to
exact.

`double_unsigned_conversion`: m2c's two-sided expansion of a double converted to `u32` (a test against a 2^31 constant
symbol, the truncation of the difference with the top bit set) and, when it follows, of that `u32` converted back to
double (a 2^32 constant added when negative), written as the casts: an N64 function was exact as
`return (f64) (u32) arg0;`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

IDENT = r'[A-Za-z_]\w*'
DO_CONSTANT = 'do_constant_body'
DOUBLE_UNSIGNED = 'double_unsigned_conversion'
FAMILIES = (DO_CONSTANT, DOUBLE_UNSIGNED)

POLL = re.compile(r'(?m)^(?P<indent>[ \t]*)do \{[ \t]*\n(?P<body>(?:[ \t]*' + IDENT
                  + r'\s*=\s*-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?\s*;[ \t]*\n)+)[ \t]*\} while \((?P<cond>.*)\);[ \t]*\n')
CONVERSION = re.compile(
    r'(?m)^(?P<indent>[ \t]*)if \((?:(?P<sym>' + IDENT + r') <= (?P<x>' + IDENT + r')|(?P<x2>' + IDENT + r') >= (?P<sym2>'
    + IDENT + r'))\) \{\s*\n\s*(?P<v>' + IDENT + r') = \(s32\) \((?P=x)?(?P=x2)? - (?:(?P=sym)|(?P=sym2))\) \| 0x80000000;'
    r'\s*\n\s*\} else \{\s*\n\s*(?P=v) = \(s32\) (?:(?P=x)|(?P=x2));\s*\n\s*\}[ \t]*\n')
BACK = re.compile(r'(?m)^[ \t]*(?P<f>' + IDENT + r') = \(f64\) (?P<v>' + IDENT + r');\s*\n\s*if \((?P=v) < 0\) \{\s*\n'
                  r'\s*(?P=f) \+= ' + IDENT + r';\s*\n\s*\}[ \t]*\n\s*return (?P=f);')


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
    for hit in POLL.finditer(clean, opening, end):
        body = source[hit.start('body'):hit.end('body')]
        if hit['cond'].count('(') != hit['cond'].count(')'):
            continue
        text = (source[:hit.start()] + f"{hit['indent']}while ({source[hit.start('cond'):hit.end('cond')]}) {{\n"
                + f"{hit['indent']}}}\n" + ''.join(hit['indent'] + line.strip() + '\n' for line in body.splitlines())
                + source[hit.end():])
        result.append((DO_CONSTANT, text))
    for hit in CONVERSION.finditer(clean, opening, end):
        x, v, indent = hit['x'] or hit['x2'], hit['v'], hit['indent']
        back = BACK.match(clean, hit.end())
        if back and back['v'] == v:
            result.append((DOUBLE_UNSIGNED, source[:hit.start()] + f'{indent}return (f64) (u32) {x};'
                           + source[back.end():]))
        result.append((DOUBLE_UNSIGNED, source[:hit.start()] + f'{indent}{v} = (u32) {x};\n' + source[hit.end():]))
    return result[:4]
