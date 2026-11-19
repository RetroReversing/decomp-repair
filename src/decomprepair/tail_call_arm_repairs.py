"""A call m2c merged after an `if`/`else` chain, made in each arm again.

When every arm of a chain ends by calling the same function with one argument that differs, gcc emits the call once and
jumps to it (cross-jumping), and m2c reads that back as a variable each arm sets and one call after the chain:

    if (a) { g(1); v = &D_1; } else { g(2); v = &D_2; }
    h(&D_0, v, 0x3840);

As written, gcc loads the call's other arguments once after the join; the game's code loads them in each arm, before
the shared jump. An N64 function went from 90.5% to 98.6% with the call written in each arm (the rest was the arms'
order). Offered when the variable is set only as each arm's last statement and read only by that call.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'call_into_arms'
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
    # a call statement right after a closing brace, one of whose arguments is a plain variable
    for call in re.finditer(r'\}[ \t]*\n(?P<indent>[ \t]*)(?P<call>' + IDENT + r'\s*\((?P<args>[^;{}]*)\))\s*;[ \t]*\n',
                            body):
        for var in dict.fromkeys(re.findall(r'(?<![\w.>&])(' + IDENT + r')(?!\s*\()', call['args'])):
            mentions = [m for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)]
            stores = list(re.finditer(r'(?m)^(?P<indent>[ \t]*)' + var + r'\s*=(?!=)\s*(?P<value>[^;{}]+);[ \t]*\n',
                                      body[:call.start()]))
            declared = re.search(r'(?m)^[ \t]*[\w ]+?[\s*]+' + var + r'\s*;[ \t]*\n', body)
            if len(stores) < 2 or not declared:
                continue
            used = [m for m in mentions if not any(s.start() <= m.start() < s.end() for s in stores)
                    and not declared.start() <= m.start() < declared.end()]
            if len(used) != 1 or not call.start('args') <= used[0].start() < call.end('args'):
                continue
            # each store is its arm's last statement
            if not all(re.match(r'\s*\}', body[s.end():]) for s in stores):
                continue
            text = source
            for s in sorted(stores, key=lambda s: -s.start()):
                arg_text = source[opening + call.start('call'):opening + call.end('call')]
                rel = used[0].start() - call.start('call')
                made = arg_text[:rel] + source[opening + s.start('value'):opening + s.end('value')].strip() + \
                    arg_text[rel + len(var):]
                at, stop = opening + s.start(), opening + s.end()
                text = text[:at] + s['indent'] + made + ';\n' + text[stop:]
            # (the stores came before the call, so its offsets moved by what the stores' text changed)
            shift = len(text) - len(source)
            line_start = opening + call.start('indent') + shift
            line_end = opening + call.end() + shift
            text = text[:line_start] + text[line_end:]
            text = text[:opening + declared.start()] + text[opening + declared.end():]
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:2]
