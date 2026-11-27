"""An empty `do { } while (0);` at the head of a `case`, so the dispatch's value is not carried into the arm.

    switch (obj->state) {
    case 1:
        do { } while (0);
        draw_background(gfxp);
        switch (menu_row) {      /* compares with 1 again */

Under KMC GCC 2.7.2 -O1 the arm of `case 1:` knows the switched value is 1, so a later compare with 1 reads the state's
register instead of loading the constant, and the state takes a saved register that moves every other allocation. The
game's loads the constant again. An empty loop after the label stops that: two N64 menu renderers needed it (383 -> 0
on the exact judge for one; the other used it with a second step). It may be what an empty debug macro left behind;
that and the compiler reason are hypotheses.

Children (`case_head_empty_loop`, bounded): the empty loop after one `case` label's statements begin, one child per
label whose arm holds a number equal to the label or another `switch`.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'case_head_empty_loop'
FAMILIES = (FAMILY,)
LIMIT = 6
EMPTY = 'do { } while (0);'
LABEL = re.compile(r'(?m)^(?P<indent>[ \t]*)case[ \t]+(?P<value>0x[0-9A-Fa-f]+|\d+)[ \t]*:[ \t]*\n')


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    result = []
    for hit in LABEL.finditer(clean, start, end):
        rest = clean[hit.end():end]
        # the arm starts here: not another label, a bare `break`, or a loop that is already there
        if re.match(r'\s*(?:case\b|default\b|break\b|do\s*\{\s*\}|\})', rest):
            continue
        opening = clean.rfind('{', start, hit.start())
        while opening >= 0 and close(clean, opening) < hit.start():
            opening = clean.rfind('{', start, opening)
        stop = close(clean, opening) if opening >= 0 else end
        following = re.compile(r'(?m)^' + re.escape(hit['indent']) + r'(?:case\b|default\b)').search(clean, hit.end(), stop)
        arm = clean[hit.end():following.start() if following else stop]
        value = int(hit['value'], 0)
        repeated = any(int(n, 0) == value for n in re.findall(r'(?<![\w.])(0x[0-9A-Fa-f]+|\d+)(?![\w.])', arm))
        if not repeated and not re.search(r'\bswitch\b', arm):
            continue
        inner = hit['indent'] + '    '
        result.append(source[:hit.end()] + inner + EMPTY + '\n' + source[hit.end():])
        if len(result) == LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}
