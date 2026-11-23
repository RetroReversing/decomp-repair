"""A float converted to an integer local once, written as the conversion at each use.

m2c (and a chain that read its output) writes the loop-invariant conversion the target hoists as a local set before the
loop: `ix = fx;` then `call(ix, ...)` in the loop. The game wrote the cast where it was used, `call((s32) fx, ...)`, and
GCC's loop pass hoists the conversion itself (`loop.c`: an invariant `fix_truncsfsi2` is a movable), which puts the
`trunc.w.s` and `mfc1` after the constants it hoists first (the `1` and `1.0f` loads), in the order it found the
conversions. A local assigned at the top stays where it was written: before the hoisted constants, with a priority
of its own in the allocation order. Measured on a 313-instruction display-list loop (KMC GCC 2.7.2, `-O2 -G0 -mips3`):
two such locals cost the preheader order (`trunc.w.s` before `addiu $s5, $zero, 1`) and the library's chain from there
stopped at 120; the casts at the calls reached 0.

`variants` takes `a = b;` or `a = (T) b;` for an integer local `a` assigned once, from a float local or parameter `b`
that is assigned at most once and not after `a` is set, and writes `((T) b)` (the declared type of `a` unless the
cast says otherwise) for every other mention of `a`, dropping the assignment and the declaration. All such locals at
once, and each alone: at most 4 proposals. A hypothesis; the exact judge decides."""
import itertools
import re

from .csource import find

FAMILY = 'conversion_local_inline'
FAMILIES = (FAMILY,)
LIMIT = 4

_ID = r'[A-Za-z_]\w*'
_INT = r'(?:unsigned\s+(?:char|short|int|long)|signed\s+(?:char|short|int|long)|[su](?:8|16|32|64)|char|short|int|long)'
_FLOAT = re.compile(r'(?:f32|f64|float|double)')
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:register[ \t]+)?(?P<type>(?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]+(?P<name>{_ID})[ \t]*;[ \t]*\n')
_SET = re.compile(rf'(?m)^[ \t]*(?P<a>{_ID})[ \t]*=[ \t]*(?:\([ \t]*(?P<cast>{_INT})[ \t]*\)[ \t]*)?(?P<b>{_ID})[ \t]*;[ \t]*\n')


def _types(text, header):
    found = {}
    for hit in _DECL.finditer(text):
        found[hit['name']] = (' '.join(hit['type'].split()), hit)
    for hit in re.finditer(rf'\b(?P<type>{_INT}|f32|f64|float|double)\s+(?P<name>{_ID})\s*[,)]', text[:text.find('{')]):
        found.setdefault(hit['name'], (' '.join(hit['type'].split()), None))
    return found


def _is_int(kind):
    return bool(re.fullmatch(_INT, kind))


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    opening = text.find('{')
    if opening < 0:
        return []
    types = _types(text, header)
    chosen = []
    for hit in _SET.finditer(text):
        a, b = hit['a'], hit['b']
        if hit.start() < opening or a not in types or b not in types or a == b:
            continue
        kind_a, decl = types[a]
        if decl is None or not _is_int(kind_a) or not _FLOAT.fullmatch(types[b][0]):
            continue
        if len(re.findall(rf'\b{re.escape(a)}\s*=[^=]', text)) != 1 or re.search(rf'&\s*{re.escape(a)}\b', text):
            continue
        sets_b = [m.start() for m in re.finditer(rf'\b{re.escape(b)}\s*(?:=[^=]|[-+*/]=|\+\+|--)', text)]
        if any(at > hit.start() for at in sets_b) or len(sets_b) > 1 or re.search(rf'&\s*{re.escape(b)}\b', text):
            continue
        uses = [m for m in re.finditer(rf'\b{re.escape(a)}\b', text) if m.start() not in (hit.start('a'), decl.start('name'))]
        if not uses:
            continue
        chosen.append((hit, decl, hit['cast'] or kind_a, b))
    out = []
    groups = [chosen] if len(chosen) > 1 else []
    groups += [[item] for item in chosen]
    for group in itertools.islice(groups, LIMIT):
        child = text
        edits = []
        for hit, decl, cast, b in group:
            a = hit['a']
            edits += [(hit.start(), hit.end(), ''), (decl.start(), decl.end(), '')]
            for use in re.finditer(rf'\b{re.escape(a)}\b', text):
                if use.start() not in (hit.start('a'), decl.start('name')):
                    edits.append((use.start(), use.end(), f'(({cast}) {b})'))
        for start, end, new in sorted(edits, reverse=True):
            child = child[:start] + new + child[end:]
        out.append((FAMILY, source[:span[0]] + child + source[span[1]:]))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
