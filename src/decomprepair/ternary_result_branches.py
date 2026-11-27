"""A stored conditional expression written as an `if`/`else` that picks into a local, then one store.

KMC GCC 2.7.2 at `-O1` writes `G = (G >= K) ? K : G + n;` (G volatile) with an annulled `beql` around the constant
arm, while the target had a plain `beqz` with the constant in the delay slot. Writing the choice as
`{ s32 v; if (G >= K) { v = K; } else { v = G + n; } G = v; }` gave the target: 200 -> 0 on a 246-instruction N64
menu routine. The other arm order (`if (G < K) { v = G + n; } else { v = K; }`) stayed at 200, so the arm order is
part of the source and both are offered. Hypothesis, not read from the compiler's source: jump.c turns
`if (c) x = K; else x = e;` into `x = K; if (!c) ...` when the constant arm is first, so the constant is set before
the branch and reorg can move it into the delay slot without annulling.

Offered for a whole-line statement `LV = COND ? A : B;` (no nested conditional) where LV is a name, an index or a
member, giving both arm orders. A candidate rewrite; the exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'ternary_result_branches'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
_LVALUE = I + r'(?:(?:\.|->)' + I + r'|\[[^][;=?]*\])*'
_PART = r'[^;?:{}\n]+'
_STATEMENT = re.compile(r'(?m)^(?P<ind>[ \t]*)(?P<lv>' + _LVALUE + r')\s*=(?!=)\s*(?P<c>' + _PART + r')\?\s*(?P<a>' +
                        _PART + r'):\s*(?P<b>' + _PART + r');[ \t]*$')
_SCALAR = r'(?:u?s?(?:8|16|32|64)|u(?:8|16|32|64)|f32|f64|float|double|(?:(?:unsigned|signed)\s+)?(?:char|short|int|long))'
LIMIT = 12


def _balanced(text):
    return text.count('(') == text.count(')') and text.count('[') == text.count(']')


def _local_type(source, lvalue):
    """The scalar type a plain name was declared with, `s32` when it cannot be told."""
    if re.fullmatch(I, lvalue):
        found = re.search(r'\b(' + _SCALAR + r')\s+(?:volatile\s+)?' + lvalue + r'\s*(?=[;,=)])', source)
        if found:
            return found[1]
    return 's32'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    chosen = next((n for n in ('chosen', 'chosen_2', 'chosen_3') if not re.search(r'\b' + n + r'\b', clean)), None)
    if not chosen:
        return []
    result = []
    for hit in _STATEMENT.finditer(clean, opening, end):
        cond, a, b = (source[hit.start(g):hit.end(g)].strip() for g in ('c', 'a', 'b'))
        if not all(_balanced(part) for part in (cond, a, b)):
            continue
        lv = source[hit.start('lv'):hit.end('lv')]
        kind = _local_type(source, lv)
        ind = hit['ind']
        bare = cond[1:-1] if cond.startswith('(') and cond.endswith(')') and _balanced(cond[1:-1]) else cond
        for test, first, second in ((bare, a, b), (negate(bare) or f'!({bare})', b, a)):
            block = (f'{ind}{{\n{ind}    {kind} {chosen};\n{ind}    if ({test}) {{\n{ind}        {chosen} = {first};\n'
                     f'{ind}    }} else {{\n{ind}        {chosen} = {second};\n{ind}    }}\n'
                     f'{ind}    {lv} = {chosen};\n{ind}}}')
            result.append((FAMILY, source[:hit.start()] + block + source[hit.end():]))
        if len(result) >= LIMIT:
            break
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
