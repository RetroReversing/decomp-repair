"""A pointer local set once to a global array, written as the array at each use.

A search or an earlier agent keeps `s16 *tbl;` and `tbl = (s16 *) D_x;` (here at the head of a loop) beside
`extern u16 D_x[];`, then reads `((u16 *) tbl)[i]` and `tbl[j]`. The local is one more value the loop pass hoists, in
the place its assignment stands: the table's `lui`/`addiu` then comes before the constants the loop's body uses first,
where a source that names the array at each read gets them hoisted in the order of those reads (a KMC GCC 2.7.2
note-sequencer of 369 instructions: 140 -> 60 with this alone, 0 after a parameter copy and a per-arm local).
`symbol_alias_array` covers `T *q = &D_x;` over a scalar extern and `symbol_base_unwrap` a local only dereferenced; a
cast of an array, assigned apart from the declaration and indexed, was neither's.

Preconditions: a plain pointer local declared without initialiser and assigned exactly once, `P = (T *) SYM;`,
`P = SYM;` or `P = &SYM[0];`, where `SYM` is declared `extern U SYM[..];`; every other mention is a read after the
assignment (never stepped, never `&P`). A use cast to the array's own element type, and a use of the same type, is the
bare symbol; any other keeps a cast.
"""
import re

from .csource import _blank, find

FAMILY = 'array_pointer_local_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'
SETTING = re.compile(rf'(?m)^[ \t]*(?P<p>{IDENT})[ \t]*=(?!=)[ \t]*(?:\([ \t]*(?P<cast>{IDENT})[ \t]*\*[ \t]*\)[ \t]*)?'
                     rf'(?:&[ \t]*(?P<first>{IDENT})[ \t]*\[[ \t]*0[ \t]*\]|(?P<symbol>{IDENT}))[ \t]*;[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    result = []
    for setting in SETTING.finditer(clean, opening, span[1]):
        local, symbol = setting['p'], setting['symbol'] or setting['first']
        array = re.search(rf'(?m)^[ \t]*extern[ \t]+(?:const[ \t]+)?(?P<type>{IDENT})[ \t]+{symbol}[ \t]*\[[^\]]*\][ \t]*;',
                          clean[:span[0]])
        declared = re.search(rf'(?m)^[ \t]*(?P<type>{IDENT})[ \t]*\*[ \t]*{local}[ \t]*;[ \t]*\n', clean[opening:span[1]])
        if not array or not declared or local == symbol:
            continue
        decl = (opening + declared.start(), opening + declared.end())
        mentions = [m for m in re.finditer(rf'(?<![\w.])(?<!->){local}\b', clean[opening:span[1]])]
        uses = [(opening + m.start(), opening + m.end()) for m in mentions]
        uses = [(a, b) for a, b in uses
                if not (decl[0] <= a < decl[1] or setting.start() <= a < setting.end())]
        if not uses or any(a < setting.end() for a, _ in uses):
            continue
        if re.search(rf'(?:(?<!&)&|\+\+|--)[ \t]*{local}\b(?![ \t]*(?:->|\[))|(?<![\w.])(?<!->){local}[ \t]*'
                     rf'(?:\+\+|--|(?:<<|>>|[-+*/%&|^])?=(?!=))', clean[setting.end():span[1]]):
            continue
        element, own = array['type'], declared['type']
        edits = [(decl[0], decl[1], ''), (setting.start(), setting.end(), '')]
        for a, b in uses:
            cast = re.search(rf'\([ \t]*\([ \t]*(?P<type>{IDENT})[ \t]*\*[ \t]*\)[ \t]*$', clean[opening:a])
            if cast and clean[b:].lstrip().startswith(')'):
                start, stop = opening + cast.start(), clean.index(')', b) + 1
                kind = cast['type']
                edits.append((start, stop, symbol if kind == element else f'(({kind} *) {symbol})'))
            else:
                edits.append((a, b, symbol if own == element else f'(({own} *) {symbol})'))
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        result.append((FAMILY, text))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 119}
