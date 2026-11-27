"""A float product plus one of its own factors, written back as `(a + 1.0f) * b`.

m2c shows what the compiler emitted, `a * s + s`. The game wrote `(a + 1.0f) * s`: GCC 2.7.2's front end distributes it
into `a * s + s` (`mul.s`, then `add.s` of the same register), and the two spellings give the same instructions but
not the same use counts. `s` is named twice in the written-out form, which raises its priority in global register
allocation. A 2430-instruction N64 effect spawner (`-O1`) had 147 register rows from two saved registers exchanged
with the written-out form, and was 4 rows from exact with the sum inside the product.

unit_term_product
    `a * b + b` and `b * a + b`, where both are names declared `f32`/`float`, becomes `(a + 1.0f) * b`. One child per
    pair of names (every place that pair appears), and one with every pair.

For finite values the two compile to the same instructions under GCC 2.7.2. Proposals only; the judge decides."""
import re

from .csource import _blank, find

FAMILY = 'unit_term_product'
FAMILIES = (FAMILY,)

FORM = re.compile(r'(?<![\w.>*/)\]])([A-Za-z_]\w*) \* ([A-Za-z_]\w*) \+ \2(?![\w.]|\s*[*/\[(.]|\s*->)'
                  r'|(?<![\w.>*/)\]])([A-Za-z_]\w*) \* ([A-Za-z_]\w*) \+ \3(?![\w.]|\s*[*/\[(.]|\s*->)')


def _floats(text):
    """The names the text declares as plain floats (locals, parameters and globals; no pointers)."""
    names = set()
    for hit in re.finditer(r'\b(?:f32|float)\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*[;,)=]', text):
        names.update(name.strip() for name in hit.group(1).split(','))
    return names


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    floats = _floats(clean)
    pairs = {}
    for hit in FORM.finditer(clean, span[0], span[1]):
        before = clean[span[0]:hit.start()].rstrip()
        if not (before.endswith(('(', ',', '=', ';', '{')) or re.search(r'\breturn$', before)):
            continue  # part of a longer expression: the sum is not this term's own
        if hit.group(1):
            other, factor = hit.group(1), hit.group(2)
        else:
            other, factor = hit.group(4), hit.group(3)
        if other in floats and factor in floats:
            pairs.setdefault((other, factor), []).append((hit.start(), hit.end(), f'({other} + 1.0f) * {factor}'))

    def apply(edits):
        out = source
        for start, end, text in sorted(edits, reverse=True):
            out = out[:start] + text + out[end:]
        return out

    found = [(FAMILY, apply(edits)) for _, edits in sorted(pairs.items())]
    if len(pairs) > 1:
        found.insert(0, (FAMILY, apply([edit for edits in pairs.values() for edit in edits])))
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
