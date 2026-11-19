"""An empty `case K: break;` that m2c invented for a switch, dropped.

m2c reads a jump table or a compare tree and sometimes emits a case that only breaks, often marked
`/* irregular */`, for a value the game's code never tested on its own. gcc 2.7.2 then compares against that
value too, and the case order and branch layout move. An N64 function switching on three values was 240 points
off with m2c's `case 0: break; /* irregular */` and exact without it. Dropping a case whose body is only `break;`
keeps the meaning when the switch has no `default` (the value then does nothing either way), so each variant drops
one such case, or all of them at once, only in switches without a `default`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'irregular_case'
FAMILIES = (FAMILY,)

SWITCH = re.compile(r'\bswitch\s*\(')
EMPTY_CASE = re.compile(r'[ \t]*\bcase\s+[^:;{}]+?:(?:[ \t]*/\*[^*]*\*/)?\s*break\s*;[ \t]*(?:/\*[^*]*\*/)?[ \t]*\n?')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for sw in SWITCH.finditer(clean, span[0], span[1]):
        paren_end = close(clean, sw.end() - 1, '(', ')')
        if not paren_end:
            continue
        opening = clean.find('{', paren_end, span[1])
        if opening < 0 or clean[paren_end:opening].strip():
            continue
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        body = clean[opening:end]
        if re.search(r'\bdefault\s*:', body):
            continue  # (with a default, an empty case keeps its value out of it)
        found = []
        for m in EMPTY_CASE.finditer(clean, opening + 1, end):
            before = clean[opening + 1:m.start()].rstrip()
            if before and not re.search(r'\b(?:break|continue)\s*;$|\b(?:return|goto)\b[^;{}]*;$', before):
                continue  # (the case before falls through into this label: dropping it would run the next case)
            found.append(m)
        if not found or len(found) > 4:
            continue
        choices = [[m] for m in found]
        if len(found) > 1:
            choices.append(found)
        for chosen in choices:
            text = source
            for m in sorted(chosen, key=lambda m: m.start(), reverse=True):
                text = text[:m.start()] + text[m.end():]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result
