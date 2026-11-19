"""A table of unknown type indexed by bytes, `*(t + &D)` with `t = i * 2`, as the array of the target's width it is.

m2c gives a symbol it can't type `extern M2C_UNK D;` (a word) and writes an element's address as a byte offset added
to `&D`, which C then scales by four. The target's own instructions name the element width (`lhu`, `sh` on
`%lo(D)`): with `t = i * 2` and halfword accesses the C meant `((u16 *) &D)[i]`. An N64 function clearing four
parallel `u16` tables in a counter loop was 68.4% with the byte offsets, 48.3% with each access cast to `u16`, and
exact as `u16` arrays indexed by a `u16` counter (after `u16_counter_loop`): gcc 2.7.2 hoists the tables' addresses
out of a loop only when it can see they're arrays it indexes.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .symbol_width_repairs import _accesses

FAMILY = 'unknown_table_index'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
SIZE = {'s32': 4, 'u32': 4, 's16': 2, 'u16': 2, 's8': 1, 'u8': 1}


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]] + clean[span[1]:]
    unknown = set(re.findall(r'(?m)^[ \t]*extern\s+M2C_UNK\s+(' + IDENT + r')\s*;', outside))
    body = clean[opening:end]
    scaled = {}
    for m in re.finditer(r'(?m)^[ \t]*(?P<t>' + IDENT + r')\s*=(?!=)\s*(?P<e>[^;{}]+?)\s*\*\s*(?P<k>[124])\s*;', body):
        if len(re.findall(r'(?<![\w.>])' + m['t'] + r'\s*=(?!=)', body)) == 1:
            scaled[m['t']] = (source[opening + m.start('e'):opening + m.end('e')].strip(), int(m['k']), m)
    hits = []
    for hit in re.finditer(r'\*\s*\(\s*(?:(?P<t1>' + IDENT + r')\s*\+\s*&\s*(?P<s1>' + IDENT + r')|&\s*(?P<s2>'
                           + IDENT + r')\s*\+\s*(?P<t2>' + IDENT + r'))\s*\)', body):
        var, symbol = hit['t1'] or hit['t2'], hit['s1'] or hit['s2']
        if symbol in unknown and var in scaled:
            hits.append((hit, var, symbol))
    if not hits:
        return []
    result = []
    # the width each symbol's own `%lo` accesses give; with none (the table's address held in a register), the scale's
    # width, unsigned and then signed
    for sign in ('u', 's'):
        edits, used = [], set()
        for hit, var, symbol in hits:
            index, k, _ = scaled[var]
            named = _accesses(asm, symbol)
            kinds = {t for t in named if SIZE[t] == k}
            if named and not kinds:
                continue  # the target's own accesses give it another width than the scale
            kind = (sorted(kinds, key=lambda t: t[0] != sign)[0] if kinds else f'{sign}{8 * k}')
            edits.append((opening + hit.start(), opening + hit.end(), f'(({kind} *) &{symbol})[{index}]'))
            used.add(var)
        if not edits:
            continue
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        text = _drop_unread(text, name, used)
        if text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result


def _drop_unread(text, name, used):
    """The byte-offset temporaries, gone when nothing reads them any more."""
    for var in used:
        clean2 = _blank(text)
        span2 = find(text, name)
        o2 = clean2.find('{', span2[0], span2[1])
        e2 = close(clean2, o2, '{', '}')
        mentions = re.findall(r'(?<![\w.>])' + var + r'\b', clean2[o2:e2])
        if len(mentions) != 2:
            continue
        line = re.search(r'(?m)^[ \t]*' + var + r'\s*=(?!=)[^;]*;[ \t]*\n', clean2[o2:e2])
        decl = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', clean2[o2:e2])
        if line and decl:
            for found in sorted((line, decl), key=lambda m: -m.start()):
                text = text[:o2 + found.start()] + text[o2 + found.end():]
    return text

