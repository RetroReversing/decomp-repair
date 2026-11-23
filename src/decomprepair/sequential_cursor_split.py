"""One list-cursor local that several separate loops walk, given a local of its own per loop (GCC 2.7.2, KMC, N64).

m2c names the cursor of every `p = list->head; while (p) { ...; p = p->next; }` walk after the register it sat in, and
the same register is the same name in every loop of the function that used it:

    var_a1 = *((void **) arg0);                 var_a1 = *((void **) (*((void **) (((u8 *) var_s6) + 8))));
    if (var_a1 != NULL) { do { ... var_a1 = *((void **) var_a1); } while (var_a1 != NULL); }

Written like that the loops are one pseudo register for global.c: one live range that covers both loops, with their
references added up (the later loop's cursor ranks with the earlier one's weight, and takes the register the earlier
one's priority gives it). The game's two loops were two variables: in a 529-instruction function the second walk's
pointer and its flag word were `$a0`/`$a1` where the first walk's were `$a1`/`$a2`, and a local of its own for the
second walk was 460 -> 405 (every row of both walks right) with nothing else changed.

When one local is walked by two or more loops of that shape (assigned, tested against NULL, then stepped through the
loop), and every other mention of it lies inside those loops, each loop after the first gets a new local of the same
type. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'sequential_cursor_split'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 8
_START = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*[^;{{}}]+;\s*if\s*\(\s*(?P=v)\s*(?:!=\s*(?:NULL|0)\s*)?\)\s*\{{')


def _walks(clean, part):
    """(variable, start of its assignment, end of the `if` block) for each guarded cursor loop."""
    found = []
    for hit in _START.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1, '{', '}')
        if not shut:
            continue
        inside = clean[hit.end():shut - 1]
        var = hit['v']
        if not re.search(r'\bdo\s*\{', inside) or not re.search(rf'(?<![\w.>]){re.escape(var)}\s*=\s*[^;]*{re.escape(var)}\b[^;]*;', inside):
            continue
        found.append((var, hit.start(), shut))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    walks = _walks(clean, part)
    out = []
    for var in dict.fromkeys(w[0] for w in walks):
        mine = [w for w in walks if w[0] == var]
        if len(mine) < 2:
            continue
        mention = re.compile(rf'(?<![\w.>]){re.escape(var)}\b')
        outside = clean[part.opening + 1:part.end]
        for _, start, end in sorted(mine, key=lambda w: -w[1]):
            outside = outside[:start - part.opening - 1] + ' ' * (end - start) + outside[end - part.opening - 1:]
        declaration = re.search(rf'(?m)^(?P<lead>[ \t]*)(?P<type>(?:\w+[ \t]+)+\**[ \t]*){re.escape(var)}[ \t]*;[ \t]*\n', clean[part.opening + 1:part.end])
        if not declaration:
            continue
        rest = outside[:declaration.start()] + outside[declaration.end():]
        if mention.search(rest):
            continue
        for number, (_, start, end) in enumerate(sorted(mine)[1:], 2):
            fresh = f'{var}_{number}'
            while re.search(rf'\b{re.escape(fresh)}\b', clean):
                number += 1
                fresh = f'{var}_{number}'
            span = source[start:end]
            renamed = mention.sub(fresh, span)
            at = part.opening + 1 + declaration.end()
            line = f"{declaration['lead']}{declaration['type']}{fresh};\n"
            out.append((FAMILY, edit(source, [(start, end, renamed), (at, at, line)])))
            if len(out) >= MAX_CHILDREN:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
