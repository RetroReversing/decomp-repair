"""A call to a private `inline` helper written as the helper's own expression.

m2c (or a search) leaves a one-expression helper (`inline static int f(u8 a, int b) { return (a != 0) && ((--g) == b); }`)
and calls it in one place where the other places in the function carry the expression itself. The compiler expands both
alike, but the call's arguments are evaluated as statements first: the values it passes (`gWorkerActive`, a constant) are
copied into the helper's parameters, so the guard carries a boolean temporary (`sltiu`) and a branch on it where the
expression written out branches on the compared value directly (`bnez $v0`). On a 370-instruction mixing function (KMC
GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) the third of three identical loops called the helper while the other two had
the expression; written out, the extra `sltiu`/`beqz` pair went and 1680 -> 1675 (one row group of several that the
chain needed).

`variants` finds helpers `inline static T f(params) { return EXPR; }` (either order of the keywords), and for each one a
child in which every call `f(a1, a2)` in the function whose arguments are identifiers, literals or casts of them is
replaced by `(EXPR)` with the parameters substituted by the arguments. The judge decides each child; a call whose argument
would be evaluated twice (a parameter read more than once in EXPR) is left alone.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'helper_call_expand'
FAMILIES = (FAMILY,)
LIMIT = 4
HELPER = re.compile(rf'(?m)^[ \t]*(?:inline\s+static|static\s+inline)\s+[\w ]+?\s+(?P<name>{IDENT})\s*\((?P<params>[^)]*)\)\s*\{{\s*return\s+(?P<expr>[^;{{}}]+);\s*\}}')
SIMPLE = re.compile(rf'^\s*(?:\(\s*[\w ]+\)\s*)?(?:{IDENT}|0[xX][0-9a-fA-F]+|\d+)\s*$')


def _python_split(text):
    parts, depth, start = [], 0, 0
    for at, ch in enumerate(text):
        depth += (ch in '([') - (ch in ')]')
        if ch == ',' and depth == 0:
            parts.append(text[start:at])
            start = at + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text):
        return [piece.strip() for piece in _scan.top_pieces(text, ',', 2) if piece.strip()]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    results = []
    for helper in HELPER.finditer(part.clean[:part.opening]):
        params = [re.sub(r'^.*?(' + IDENT + r')\s*$', r'\1', p.strip()) for p in _split(helper['params'])]
        expr = helper['expr'].strip()
        if not params or any(len(re.findall(rf'(?<![\w.>]){re.escape(p)}\b', expr)) > 1 for p in params):
            continue
        edits = []
        for call in re.finditer(rf'(?<![\w.>]){re.escape(helper["name"])}\s*\(', part.clean[part.opening:part.end]):
            at = part.opening + call.start()
            stop = close(part.clean, part.opening + call.end() - 1, '(', ')')
            if not stop:
                continue
            args = _split(part.clean[part.opening + call.end():stop - 1])
            if len(args) != len(params) or not all(SIMPLE.match(a) for a in args):
                continue
            body = expr
            for p, a in zip(params, args):
                body = re.sub(rf'(?<![\w.>]){re.escape(p)}\b', a.replace('\\', '\\\\'), body)
            edits.append((at, stop, f'({body})'))
        if edits:
            text = edit(source, edits)
            if text != source and (FAMILY, text) not in results:
                results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # the registry: no caller wiring (registry.py)
