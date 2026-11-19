"""An address m2c kept in a variable across a loop, written where it's used.

m2c names `p + 0x24` once before a `do` loop and again after the loop advances `p`:

    var_a0 = var_s0 + 0x24;
    do {
        if (f(var_a0, ...) ...) ...
        var_s0 = *var_s0;
        var_a0 = var_s0 + 0x24;
    } while (var_s0 != NULL);

The game computed it at its use: as a variable of its own it stayed in `$a0` and gcc hoisted a constant past it (an N64
function was 94.5%, exact this way). Offered when every assignment of the variable is the same `base + constant`, each
right before a `do` or right after an assignment to the base, and the variable is read in one place.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loop_address_inline'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


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
    for declared in re.finditer(r'(?m)^[ \t]*[\w ]+?[\s*]+(' + IDENT + r')\s*;[ \t]*\n', body):
        var = declared[1]
        stores = list(re.finditer(r'(?m)^[ \t]*' + var + r'\s*=(?!=)\s*(?P<base>' + IDENT + r')\s*\+\s*'
                                  r'(?P<k>0[xX][0-9a-fA-F]+|\d+)\s*;[ \t]*\n', body))
        if len(stores) < 2 or len({(s['base'], s['k']) for s in stores}) != 1:
            continue
        base, k = stores[0]['base'], stores[0]['k']
        mentions = [m for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)
                    if not declared.start() <= m.start() < declared.end()
                    and not any(s.start() <= m.start() < s.end() for s in stores)]
        if len(mentions) != 1:
            continue
        ok = True
        for s in stores:
            after = re.match(r'\s*do\b', body[s.end():])
            before = re.search(r'(?<![\w.>])' + base + r'\s*=(?!=)[^;]*;\s*$', body[:s.start()])
            if not (after or before):
                ok = False
        if not ok:
            continue
        use = opening + mentions[0].start()
        edits = [(use, use + len(var), f'{base} + {k}'), (opening + declared.start(), opening + declared.end(), '')]
        edits += [(opening + s.start(), opening + s.end(), '') for s in stores]
        text = source
        for at, stop, new in sorted(edits, reverse=True):
            text = text[:at] + new + text[stop:]
        result.append((FAMILY, text))
    return result[:2]
