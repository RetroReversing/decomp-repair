"""A call's span of two arguments (`i * W`, `i * W + W - 1`) staged in halfword locals, the far one built on the near.

Tile loaders take a rectangle as its first and last texel, and the game's source often held the corners in locals of
their own:

    load(p, s * 32, t * 32, s * 32 + 31, t * 32 + 31);   ->   {
                                                                  s16 span0 = s * 32;
                                                                  s16 span1 = t * 32;
                                                                  s16 end0 = span0 + 32;
                                                                  s16 end1 = span1 + 32;
                                                                  load(p, span0, span1, end0 - 1, end1 - 1);
                                                              }

Written out in the call, the compiler folds the far corner to `i * W + (W - 1)`; with the locals it keeps `+ W` and
`- 1` apart, as a 135-instruction N64 texture-tile display list does (gcc 2.7.2 KMC, `-O1`: 1900 -> 0 from the call
with the corners written out). Every pair is offered together and the first alone, as halfwords and as words."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'call_span_locals'
FAMILIES = (FAMILY,)
LIMIT = 8
_TYPES = ('s16', 'u16', 's32')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}
_NUMBER = r'(?:0[xX][\da-fA-F]+|\d+)'
_NEAR = re.compile(rf'(?P<index>[A-Za-z_]\w*)\s*(?:\*\s*(?P<width>{_NUMBER})|<<\s*(?P<shift>{_NUMBER}))')


def _arguments(clean, opening, stop):
    """[(start, end)] of the top-level arguments between a call's parentheses."""
    spans, depth, last = [], 0, opening + 1
    for at in range(opening + 1, stop - 1):
        if clean[at] in '([{':
            depth += 1
        elif clean[at] in ')]}':
            depth -= 1
        elif clean[at] == ',' and not depth:
            spans.append((last, at))
            last = at + 1
    return spans + [(last, stop - 1)]


def _plain(text):
    return re.sub(r'\s+', '', text)


def _far_forms(index, width, near):
    """The spellings of the last element of a span of `width` that starts at `near`."""
    base = _plain(near)
    return {f'{base}+{width - 1}', f'({base})+{width - 1}', f'{base}+{width}-1', f'({base}+{width})-1',
            f'(({index}+1)*{width})-1', f'({index}+1)*{width}-1'}


def _pairs(arguments):
    """[(near argument, far argument, near text, width)] of the spans among the arguments."""
    found, used = [], set()
    for i, text in enumerate(arguments):
        near = _NEAR.fullmatch(text.strip())
        if not near:
            continue
        width = int(near['width'], 0) if near['width'] else 1 << int(near['shift'], 0)
        if width < 2:
            continue
        forms = _far_forms(near['index'], width, text.strip())
        for j, other in enumerate(arguments):
            if j != i and j not in used and _plain(other) in forms:
                found.append((i, j, text.strip(), width))
                used.add(j)
                break
    return found


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for call in re.finditer(r'(?<![\w.>])([A-Za-z_]\w*)\s*\(', clean[span[0]:span[1]]):
        start = span[0] + call.start()
        opening = span[0] + call.end() - 1
        if call[1] in _KEYWORDS or clean[:start].rstrip()[-1:] not in (';', '{', '}', ':'):
            continue
        stop = close(clean, opening, '(', ')')
        if not stop or not clean[stop:].lstrip().startswith(';'):
            continue
        end = clean.index(';', stop) + 1
        spans = _arguments(clean, opening, stop)
        pairs = _pairs([source[a:b] for a, b in spans])
        if not pairs or re.search(r'\bspan0\b|\bend0\b', clean):
            continue
        indent = re.search(r'[ \t]*$', source[:start])[0]
        for chosen in ([pairs, pairs[:1]] if len(pairs) > 1 else [pairs]):
            for kind in _TYPES:
                statement = source[start:end]
                edits = []
                for k, (i, j, _, _) in enumerate(chosen):
                    edits += [(spans[i], f'span{k}'), (spans[j], f'end{k} - 1')]
                for (a, b), text in sorted(edits, reverse=True):
                    lead = re.match(r'\s*', source[a:b])[0]
                    statement = statement[:a - start] + lead + text + statement[b - start:]
                lines = [f'{kind} span{k} = {near};' for k, (_, _, near, _) in enumerate(chosen)]
                lines += [f'{kind} end{k} = span{k} + {width};' for k, (_, _, _, width) in enumerate(chosen)]
                body = ''.join(f'\n{indent}    {line}' for line in lines + [statement])
                out.append((FAMILY, source[:start] + '{' + body + f'\n{indent}}}' + source[end:]))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
