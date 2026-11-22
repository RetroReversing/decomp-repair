"""An assignment sunk past the guard that follows it, to the end of its block (live ranges decide the registers).

    else {                          else {
        found = NULL;                   if (limit >= key) { next = next->link; if (next) continue; }
        if (limit >= key) {   ->        found = NULL;
            next = ...; if (next) continue;
        }
    }                               }

KMC GCC 2.7.2 ranks saved/argument registers by live length, and a value assigned before a compare is live across the
compare's operands: `found = NULL` ahead of `limit >= key` kept `found` off `$v0` (where the compare's temporary
lives), so the found pointer took a higher register and every later one shifted (1705 -> 1330, one step of a 0 match).
After the guard the assignment shares `$v0` with it, and the target's `move $v0,$zero` sits in the guard's delay slot.
The rewrite is offered when the guard is the block's last statement and neither the guard's condition nor its body
mention the variable; the paths that leave the block through `continue` skip the assignment, so it is a candidate for
the judge, not an equivalence proof.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'assignment_guard_sink'
FAMILIES = (FAMILY,)
LIMIT = 6
_ASSIGN = re.compile(rf'(?P<var>{IDENT})\s*=(?!=)\s*(?P<rhs>[\w\s.+\-]+|\(\(void\s*\*\)\s*0\)|NULL)\s*;')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, result = part.clean, []
    for hit in _ASSIGN.finditer(clean, part.opening + 1, part.end):
        if clean[:hit.start()].rstrip()[-1:] not in ';{}' or hit['var'] in {'return', 'else'}:
            continue
        guard = re.compile(r'\s*if\s*\(').match(clean, hit.end())
        if not guard:
            continue
        opening = guard.end() - 1
        condition = close(clean, opening)
        body = re.compile(r'\s*\{').match(clean, condition) if condition else None
        if not body:
            continue
        stop = close(clean, body.end() - 1, '{', '}')
        if not stop or re.match(r'\s*else\b', clean[stop:stop + 8]) or not re.match(r'\s*\}', clean[stop:]):
            continue
        inside = clean[opening:stop]
        if re.search(rf'\b{re.escape(hit["var"])}\b', inside) or not re.search(r'\bcontinue\b', inside):
            continue
        indent = re.search(r'[ \t]*$', clean[:hit.start()])[0]
        line = source[hit.start():hit.end()]
        cut = hit.end() + (1 if clean[hit.end():hit.end() + 1] == '\n' else 0)
        start = hit.start() - len(indent)
        result.append((FAMILY, edit(source, [(start, cut, ''), (stop, stop, f'\n{indent}{line}')])))
    return list(dict.fromkeys(result))[:LIMIT]
