"""A word packed as `((a | b) | K)` written so the constant joins the lower field first.

m2c writes a packed store as `x = (hi_part | (lo_part << 8)) | 0x19;`. gcc 2.7.2 keeps that association: the `or` of
the two fields, then an `ori` on the result. A KMC N64 function's target does the `ori` on the low field before the
`or`, and no spelling of the sum changes it because combine reassociates a one-line expression. A local that holds the
low field with its constant ends the reassociation (160 -> 95 on that function; the rest of its difference was elsewhere):

    x = (a | b) | 0x19;        ->       { u32 q = b | 0x19;  x = a | q; }
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'or_constant_stage'
FAMILIES = (FAMILY,)

NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
STATEMENT = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^;=\n]+?)\s*=(?!=)\s*'
                       rf'(?P<rhs>\([^;]*\))\s*\|\s*(?P<k>{NUMBER})\s*;')
KEYWORD = re.compile(r'\s*(?:if|while|for|return|switch|else|do|case)\b')


def _python_split(inner):
    """The last top-level `|` of an expression: (left, right), or None."""
    depth = 0
    cut = None
    for at, char in enumerate(inner):
        depth += char in '(['
        depth -= char in ')]'
        if char == '|' and depth == 0 and inner[at - 1:at] != '|' and inner[at + 1:at + 2] != '|':
            cut = at
    if cut is None:
        return None
    return inner[:cut].strip(), inner[cut + 1:].strip()


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(inner):
        cut = None
        for at in _scan.top_offsets(inner, '|', 2):
            if inner[at - 1:at] != '|' and inner[at + 1:at + 2] != '|':
                cut = at
        if cut is None:
            return None
        return inner[:cut].strip(), inner[cut + 1:].strip()


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    result = []
    for hit in STATEMENT.finditer(clean, opening, span[1]):
        if KEYWORD.match(hit['lhs']):
            continue
        rhs = hit['rhs']
        if close(rhs, 0) != len(rhs):
            continue  # the parenthesis closes before the `| K`: not one group
        halves = _split(rhs[1:-1])
        if not halves or not halves[0] or not halves[1]:
            continue
        left, right = halves
        indent = hit['indent']
        lhs = source[hit.start('lhs'):hit.end('lhs')].rstrip()
        block = (f'{indent}{{\n{indent}  u32 __repair_or = {right} | {hit["k"]};\n'
                 f'{indent}  {lhs} = {left} | __repair_or;\n{indent}}}')
        text = source[:hit.start()] + block + source[hit.end():]
        if text not in [t for _, t in result]:
            result.append((FAMILY, text))
        if len(result) >= 3:
            break
    return result
