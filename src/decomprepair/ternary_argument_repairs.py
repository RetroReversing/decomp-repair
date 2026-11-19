"""A value m2c chose in an `if`/`else` and used once, written as `?:` where it is used.

m2c writes a choice between two values, used once in the next statement, as an `if`/`else` filling a variable:

    if (2U > i) {
        var_a2 = (&D_8011F160)[i];
    } else {
        var_a2 = (i * 0xC) + D_8011F280;
    }
    g(a, b, var_a2, c);

gcc 2.7.2 gives the variable a register of its own and joins the arms at it; written as the argument it was,
`g(a, b, (2U > i) ? ... : ..., c)`, each arm computes straight into the argument's register. An N64 function was 98.7%
as m2c wrote it, 99.6% with this alone and exact once its other leftovers went. Offered when the variable is assigned
only in the two arms and read only in the statement right after.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'ternary_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
SHAPE = re.compile(r'\bif\s*\(')


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
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        cond_open = hit.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close:
            continue
        arm = re.compile(r'\s*\{\s*(' + IDENT + r')\s*=(?!=)\s*([^;{}]+);\s*\}').match(clean, cond_close)
        if not arm:
            continue
        other = re.compile(r'\s*else\s*\{\s*(' + IDENT + r')\s*=(?!=)\s*([^;{}]+);\s*\}').match(clean, arm.end())
        if not other or other[1] != arm[1]:
            continue
        var = arm[1]
        # the statement right after, which must read the variable exactly once
        after = re.compile(r'\s*([^;{}]*);').match(clean, other.end())
        if not after or len(re.findall(r'(?<![\w.>])' + var + r'\b', after[1])) != 1:
            continue
        if re.search(r'(?<![\w.>])' + var + r'\s*=(?!=)', after[1]):
            continue
        # nowhere else in the function: its declaration, the two arms and that one use
        mentions = re.findall(r'(?<![\w.>])' + var + r'\b', body)
        if len(mentions) != 4:
            continue
        declared = re.search(r'(?m)^[ \t]*((?:[\w ]+?)[\s*]*?)\s*\b' + var + r'\s*;', body)
        kind = ' '.join(declared[1].split()) if declared else None
        if not kind:
            continue
        cast = f'({kind})'
        condition = source[cond_open + 1:cond_close - 1].strip()
        first = source[arm.start(2):arm.end(2)].strip()
        second = source[other.start(2):other.end(2)].strip()
        choice = f'({condition}) ? {cast} ({first}) : {cast} ({second})'
        use = re.search(r'(?<![\w.>])' + var + r'\b', source[after.start(1):after.end(1)])
        at = after.start(1) + use.start()
        statement = source[after.start(1):at] + choice + source[at + len(var):after.end(1)]
        line = source.rfind('\n', 0, hit.start()) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        text = source[:line] + indent + statement + ';' + source[after.end():]
        # the variable's declaration goes too
        declaration = re.search(r'(?m)^[ \t]*(?:[\w ]+?)[\s*]*\b' + var + r'\s*;[ \t]*\n', text[opening:])
        if declaration:
            text = text[:opening + declaration.start()] + text[opening + declaration.end():]
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result
