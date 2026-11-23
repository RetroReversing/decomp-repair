"""m2c's branch-free clamp to zero, written as the compare the game had.

gcc 2.7.2 compiles `if (x < 0) x = 0;` as a `slt`/`bnel` pair, or (with the clamp's operand still live) as the
`nor`, `sra 31`, `and` triple m2c reads back as `x & ((s32) ~x >> 0x1F)`. The game's own statement was the compare; the
bit trick is m2c's reading of the triple. Written as the trick it compiles to the same three instructions only when
nothing else decides the order, and in a tile-rectangle builder it was one of six edits between a draft's
macro form and the match (a clamp of `x - 1` at the left edge and of `y - 1` at the top: 6765 -> 6000 on a
315-instruction function, whose loop pass and register order follow the compare's shape, not the mask's).

Two spellings, both read as statements:

    t = a - 1;                     ->   t = a - 1;
    r = t & ((s32) ~t >> 0x1F);          if (r < 0) { r = 0; }

and the in-place `t = t & ((s32) ~t >> 0x1F);` -> `if (t < 0) { t = 0; }`. The first needs the assignment to `t` right
before the idiom and no other mention of `t` (it is a copy m2c made only for the mask: the pair becomes one
assignment to the result and the compare). `r` that is not a signed integer gets the cast in the compare, which is the
sign test the mask makes. One proposal per site (at most 4), and all of them together. A hypothesis about the
compiler's choice; the exact judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'clamp_zero_idiom'
FAMILIES = (FAMILY,)
LIMIT = 4

_ID = r'[A-Za-z_]\w*'
_SIGNED = re.compile(r'(?:signed\s+)?(?:s8|s16|s32|s64|int|long|short|char)')
_STATEMENT = re.compile(rf'(?P<r>{_ID})\s*=\s*(?P<rhs>[^;{{}}]+?)\s*;')
_IDIOM = re.compile(rf'(?P<a>{_ID})&(?:\(s32\)|\(int\)|s32|int)~(?P=a)>>(?:0x1[fF]|31)')


def _flat(text):
    return re.sub(r'[\s()]', '', text)


def _declared(clean, body_start, name):
    """The declared type of `name` in the function (a local or a parameter), or None."""
    for hit in re.finditer(rf'(?:^|[;{{(,])\s*(?:register\s+)?(?P<t>(?:unsigned\s+|signed\s+)?{_ID}(?:\s+{_ID})?)\s+\**\s*{re.escape(name)}\s*[;,)=\[]',
                           clean, re.M):
        text = ' '.join(hit['t'].split())
        if text not in ('return', 'else'):
            return text
    return None


def _uses(clean, name):
    return [m.start() for m in re.finditer(rf'(?<![\w.]){re.escape(name)}\b', clean)]


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body_start, end = part.opening + 1, part.end
    function = clean[part.opening:end]
    sites = []
    for hit in _STATEMENT.finditer(clean, body_start, end):
        match = _IDIOM.fullmatch(_flat(hit['rhs']))
        if not match:
            continue
        result, a = hit['r'], match['a']
        kind = _declared(clean[:end], body_start, result)
        if kind is None:
            continue
        compare = f'{result} < 0' if _SIGNED.fullmatch(kind) else f'(s32) {result} < 0'
        guard = f'if ({compare}) {{ {result} = 0; }}'
        if result == a:
            sites.append((hit.start(), hit.end(), guard, None))
            continue
        # the copy `a = EXPR;` right before, mentioned nowhere else in the function
        before = clean[body_start:hit.start()].rstrip()
        if not before.endswith(';'):
            continue
        last = max(before.rfind(';', 0, -1), before.rfind('{'), before.rfind('}'))
        prior = _STATEMENT.fullmatch(before[last + 1:].strip())
        if not prior or prior['r'] != a:
            continue
        first = body_start + last + 1
        mentions = _uses(function, a)
        declaration = re.search(rf'(?m)^[ \t]*(?:register[ \t]+)?[\w ]+?\b{re.escape(a)}[ \t]*;[ \t]*\n', function)
        if len(mentions) != 3 + (1 if declaration else 0) or re.search(rf'&\s*{re.escape(a)}\b', function):
            continue
        start = first
        while clean[start] in ' \t\n':
            start += 1
        child = f'{result} = {prior["rhs"]}; {guard}'
        sites.append((start, hit.end(), child, declaration and (part.opening + declaration.start(), part.opening + declaration.end())))
    if not sites:
        return []
    sites = sites[:LIMIT]
    out = []
    groups = [sites] if len(sites) > 1 else []
    groups += [[site] for site in sites]
    for group in groups:
        edits = []
        for start, stop, text, declaration in group:
            edits.append((start, stop, text))
            if declaration:
                edits.append((declaration[0], declaration[1], ''))
        out.append((FAMILY, edit(source, edits)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 99}  # the registry: no caller wiring (registry.py)
