"""A running total m2c split into a temporary half way, written back as the one variable.

m2c names each value of a register separately, so a total stepped twice in a block comes back through a second name:

    t = total + size;                    total += size;
    use((t + 0xF) >> 4);        ->       use((total + 0xF) >> 4);
    total = t + other;                   total += other;

As two locals the value has two pseudos, each with a short life, and the allocator gives the pair other registers than
the one long-lived total; through `a = t + y` no family folds it back (`accumulate_separate_dest` goes the other way).
A loader on SN GCC 2.8.1 (`-G0 -mips3 -O2`) kept 27 register rows until its heap offset was one variable again.

Taken when `t = a + x;` and `a = t + y;` stand in the same block, every mention of `t` lies between them (apart from
its declaration), `a` is not mentioned between them and the stretch has no label or jump. The judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'split_accumulator'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_SET = re.compile(rf'(?m)^(?P<pad>[ \t]*)(?P<t>{_ID})[ \t]*=[ \t]*(?P<a>{_ID})[ \t]*(?P<op>[+-])[ \t]*(?P<x>[^;{{}}\n]+);')
LIMIT = 4


def _edits(clean, opening, end, first):
    """The edits that fold the temporary of `first` back into its source variable, or None."""
    t, a = first['t'], first['a']
    if t == a:
        return None
    last = re.compile(rf'(?<![\w.>]){a}[ \t]*=[ \t]*{t}[ \t]*(?P<op>[+-])[ \t]*(?P<y>[^;{{}}\n]+);').search(
        clean, first.end(), end)
    declared = re.compile(rf'(?m)^[ \t]*(?:{_ID}[ \t]+)+{t}[ \t]*;[ \t]*\n').search(clean, opening, end)
    if not last or not declared:
        return None
    between = clean[first.end():last.start()]
    depth = 0
    for brace in re.findall(r'[{}]', between):
        depth += 1 if brace == '{' else -1
        if depth < 0:
            return None
    if depth or re.search(rf'(?<![\w.>]){a}\b|(?<![\w.])(?:goto|continue|break|return|case|default)\b'
                          rf'|(?m:^\s*\w+\s*:(?!:))', between):
        return None
    word = rf'(?<![\w.>]){t}\b'
    if re.search(rf'(?<![\w.>])(?:{t}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{t}\b)|(?<!&)&\s*{t}\b',
                 between):
        return None
    if re.search(rf'(?<![\w.>])(?:{t}|{a})\b', first['x'] + ' ' + last['y']):
        return None
    inside = len(re.findall(word, clean[first.start():last.end()]))
    if len(re.findall(word, clean[opening:end])) != inside + 1:
        return None
    edits = [(declared.start(), declared.end(), ''),
             (first.start('t'), first.end(), f'{a} {first["op"]}= {first["x"].strip()};'),
             (last.start(), last.end(), f'{a} {last["op"]}= {last["y"].strip()};')]
    edits += [(first.end() + use.start(), first.end() + use.end(), a) for use in re.finditer(word, between)]
    return edits


def _apply(source, edits):
    for a, b, text in sorted(edits, reverse=True):
        source = source[:a] + text + source[b:]
    return source


def variants(source, name):
    """Proposals: each split total as one variable."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    out = []
    for first in _SET.finditer(clean, opening, span[1]):
        edits = _edits(clean, opening, span[1], first)
        if edits:
            out.append((FAMILY, _apply(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
