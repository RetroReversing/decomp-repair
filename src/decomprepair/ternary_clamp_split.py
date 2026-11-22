"""A clamp `v = (v < n) ? v : 0;` as a copy and a guarded default: `t = v; if (v >= n) t = 0;`, the later reads on `t`.

KMC GCC 2.7.2 expands the conditional expression as `v = 0; v = v & -(v < n)` and, since the result goes back into
`v`, allocates the `and` straight into `v`'s register; both call arms that read it then take it from there. The
target's two arms read the clamped value from two pseudos: the `and` lands in a temporary ($t1), the clamped variable
is a copy of it ($a3, set at once and read by one arm), and the other arm copies the temporary into its argument
register. Written as the copy and the guarded default (`t = v; if (v >= n) t = 0;`, every later read of `v` on `t`)
the compiler keeps two pseudos, and the allocator gives the argument register to the one the target did. Measured
on a 114-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) whose next-frame index was clamped
before two calls: 435 -> 0. Other spellings that kept the ternary (a copy back into `v`, the `& -(v < n)` form, which
arm reads which variable, where the new local was declared) all stayed at 435 or went to 730-910; the `if` form was
the only one of 40 that reached 0. Hypothesis, not read from the compiler's source: cse's choice of the canonical
register of the copy's equivalence class (the one with the later last use) decides which arm reads which.

Offered for a statement `v = COND ? v : D;` or `v = COND ? D : v;` (D a literal or a name, COND without a call) at the
top level of the function body, when `v` is a plain integer local that is not written again afterwards and whose
address is never taken. The reads after the statement move to a new local declared beside `v`. A candidate rewrite;
the exact judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'ternary_clamp_split'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
_LITERAL = r'-?(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_TYPE = r'(?:(?:unsigned|signed|const|register|volatile|static|short|long|int|char)\s+)*' + I


def _free_name(text, base):
    for suffix in ('', '_2', '_3', '_4'):
        if not re.search(r'\b' + base + suffix + r'\b', text):
            return base + suffix
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
    shape = re.compile(r'(?m)^(?P<ind>[ \t]*)(?P<v>' + I + r')\s*=\s*\(?(?P<c>[^;?\n]+?)\)?\s*\?\s*'
                       r'(?P<a>' + _LITERAL + '|' + I + r')\s*:\s*(?P<b>' + _LITERAL + '|' + I + r')\s*;[ \t]*\n')
    result = []
    for hit in shape.finditer(clean, opening, end):
        v, cond, a, b = hit['v'], hit['c'].strip(), hit['a'], hit['b']
        if {a, b} != {v, a if a != v else b} or a == b or not re.search(r'\b' + v + r'\b', cond):
            continue
        if re.search(I + r'\s*\(|\+\+|--|[^=!<>]=[^=]', cond):
            continue
        # The statement sits at the function's top level (no loop or branch around it).
        depth = clean[opening:hit.start()].count('{') - clean[opening:hit.start()].count('}')
        if depth != 1:
            continue
        tail = clean[hit.end():end]
        if not re.search(r'\b' + v + r'\b', tail):
            continue
        if re.search(r'(?:&\s*' + v + r'\b)|(?:\b' + v + r'\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=|<<=|>>=))|(?:(?:\+\+|--)\s*' + v + r'\b)', tail):
            continue
        decl = re.search(r'(?m)^(?P<ind>[ \t]*)(?P<type>' + _TYPE + r')\s+(?P<names>[^;(){}\n]*\b' + v + r'\b[^;(){}\n]*);[ \t]*\n',
                         clean[opening:hit.start()])
        if not decl or re.search(r'[*\[=]', decl['names']) and re.search(r'[*\[=][^,]*\b' + v + r'\b|\b' + v + r'\b\s*[\[=]', decl['names']):
            continue
        if re.search(r'\b(?:float|double|f32|f64|void)\b', decl['type']):
            continue
        new = _free_name(clean, v + '_clamped')
        if not new:
            continue
        # `v = COND ? v : D` keeps v when COND holds, so the default is under the inverse test; `COND ? D : v` under COND.
        default = b if a == v else a
        guard = (negate(cond) or f'!({cond})') if a == v else cond
        ind = hit['ind']
        form = f'{ind}{new} = {v};\n{ind}if ({guard}) {{\n{ind}    {new} = {default};\n{ind}}}\n'
        rest = re.sub(r'\b' + v + r'\b', new, source[hit.end():end])
        text = source[:opening + decl.end()] + f'{decl["ind"]}{decl["type"]} {new};\n' + \
            source[opening + decl.end():hit.start()] + form + rest + source[end:]
        result.append((FAMILY, text))
    return result[:1]
