"""A counted `for` loop written as the guarded `do { } while` it can differ from.

    for (j = 0; j < count; j++) { B }  ->  j = 0; if (j < count) { do { B j++; } while (j < count); }

GCC copies a `for`'s entry test in front of the loop itself (jump.c); written by hand the guard is a statement of the
enclosing block instead. When the bound is a global read in an outer loop, the target held its `%hi` in one saved
register for the whole outer loop, while the `for` made a second one for the inner loop (a ninth saved register and a
larger frame). On an 84-instruction pairwise collision test (SN GCC 2.8.1, `-G0 -mips3 -O2`, N64) the guarded form was
421 -> 0. Which compiler pass decides it is a hypothesis; the exact judge decides.

counted_for_guarded_do
    Each braced `for (v = 0; v < B; v++)` (also `++v`, `v += 1`) with no call in `B` and no `continue` in its body,
    one child per loop, written as above. `guarded_do_to_for` and `guarded_do_for` go the other way;
    `guarded_cursor_do_loop` needs pointers stepped in the `for`'s header.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'counted_for_guarded_do'
FAMILIES = (FAMILY,)
LIMIT = 6
_FOR = re.compile(rf'\bfor\s*\(\s*(?P<v>{IDENT})\s*=\s*0\s*;\s*(?P=v)\s*<(?![<=])\s*(?P<bound>[^;{{}}]+?)\s*;\s*'
                  rf'(?:(?P=v)\s*\+\+|\+\+\s*(?P=v)|(?P=v)\s*\+=\s*1)\s*\)\s*\{{')
_CALL = re.compile(rf'{IDENT}\s*\(')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    results = []
    for hit in _FOR.finditer(part.clean, part.opening, part.end):
        brace = hit.end() - 1
        done = close(part.clean, brace, '{', '}')
        if not done or _CALL.search(hit['bound']) or re.search(r'\bcontinue\b', part.clean[brace:done]):
            continue
        before = part.clean[part.opening:hit.start()].rstrip()
        if not before.endswith((';', '{', '}')):
            continue  # an unbraced `if` or `else` would take only the first statement
        v = hit['v']
        bound = source[hit.start('bound'):hit.end('bound')]
        inside = source[brace + 1:done - 1].rstrip()
        text = f'{v} = 0;\nif ({v} < {bound}) {{\ndo {{{inside}\n{v}++;\n}} while ({v} < {bound});\n}}'
        results.append((FAMILY, edit(source, [(hit.start(), done, text)])))
        if len(results) == LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
