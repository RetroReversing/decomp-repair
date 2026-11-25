"""m2c's result flag set inside a comma in its condition, written as the two returns it came from.

`return A && B;`-shaped code, with calls in both tests, comes back from m2c as

    if (!(A) || (var_v0 = 1, !(B))) {
        var_v0 = 0;
    }
    return var_v0;

and gcc keeps the flag in a saved register across the second call. An N64 function was 96.8% so and exact as
`if ((A) && (B)) { return 1; } return 0;`.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'comma_flag_condition'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
N = r'-?(?:0[xX][0-9a-fA-F]+|\d+)'


def _python_terms(text):
    """`text` cut at its top-level `||`."""
    parts, depth, begin, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        depth += (ch in '([') - (ch in ')]')
        if depth == 0 and text.startswith('||', i):
            parts.append(text[begin:i])
            begin = i + 2
            i += 2
            continue
        i += 1
    return parts + [text[begin:]]


_terms = _python_terms
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _terms(text):
        found = _scan.split_top(text, '||', True)
        return _python_terms(text) if found is NotImplemented else found


def _positive(term):
    term = term.strip()
    while term.startswith('(') and close(term, 0) == len(term):
        term = term[1:-1].strip()
    if term.startswith('!(') and close(term, 1) == len(term):
        return term[2:-1].strip()
    return None


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
    for hit in re.finditer(r'(?m)^(?P<ind>[ \t]*)if \(', clean[opening:end]):
        at = opening + hit.end() - 1
        cond_end = close(clean, at)
        if not cond_end:
            continue
        rest = re.compile(r'\s*\{\s*(?P<v>' + I + r')\s*=\s*(?P<c0>' + N + r')\s*;\s*\}\s*return\s+(?P=v)\s*;').match(clean, cond_end)
        if not rest:
            continue
        var, c0 = rest['v'], rest['c0']
        positives, c1 = [], None
        for term in _terms(source[at + 1:cond_end - 1]):
            inner = term.strip()
            while inner.startswith('(') and close(inner, 0) == len(inner):
                inner = inner[1:-1].strip()
            parts = m2cfix._split_top_level(inner)
            if len(parts) == 2 and re.fullmatch(r'\s*' + var + r'\s*=\s*' + N + r'\s*', parts[0]):
                c1 = parts[0].split('=')[1].strip()
                term = parts[1]
            positive = _positive(term)
            if positive is None:
                break
            positives.append(positive)
        else:
            if c1 is None or re.search(r'\b' + var + r'\b', ' '.join(positives)):
                continue
            ind = hit['ind']
            joined = ' && '.join(f'({p})' for p in positives)
            replacement = f'if ({joined}) {{\n{ind}    return {c1};\n{ind}}}\n{ind}return {c0};'
            text = source[:opening + hit.start('ind') + len(ind)] + replacement + source[rest.end():]
            decl = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', text[opening:])
            if decl and len(re.findall(r'\b' + var + r'\b', _blank(text)[opening:])) == 1:
                text = text[:opening + decl.start()] + text[opening + decl.end():]
            result.append((FAMILY, text))
    return result[:2]
