"""A counted loop that indexes `base->member[i].field` written as a pointer walked beside the counter.

    for (m = 0; m < 3; m++) { if (w < tri->v[m].s || h < tri->v[m].t) ... }

shares one `&tri->v[m]` address between the two reads and keeps the base pointer's offsets (`lh 4($v1); lh 6($v1)`).
The target's `addiu $v1, $a2, 6; lh -2($v1); lh 0($v1)` is the loop pass reducing the reads of a walked pointer:

    q = tri->v;
    for (m = 0; m < 3; m++, q++) { if (w < q->s || h < q->t) ... }

(SN GCC 2.8.1, one N64 model loader: 500 -> exact with the other steps.) Offered when the counter is used in the body only
as that subscript, of one array whose element type is declared in the source.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'element_member_walk'
FAMILIES = (FAMILY,)

_FOR = re.compile(r'(?m)^(?P<ind>[ \t]*)for[ \t]*\((?P<init>[ \t]*(?P<i>[A-Za-z_]\w*)[ \t]*=[ \t]*0[ \t]*);'
                  r'(?P<cond>[^;()]*);[ \t]*(?P<step>(?P=i)\+\+|\+\+(?P=i))[ \t]*\)[ \t]*\{')
POINTER = 'repair_walk'


def _element_type(source, base):
    """The element type of `a->member[...]` / `a.member[...]` (a member array) or of a pointer `a[...]`."""
    if '->' in base or '.' in base:
        member = re.split(r'->|\.', base)[-1]
        found = {m[1] for m in re.finditer(rf'\b([A-Za-z_]\w*)[ \t]+{member}[ \t]*\[[ \t]*\w*[ \t]*\][ \t]*;', source)}
    else:
        found = {m[1] for m in re.finditer(rf'\b([A-Za-z_]\w*)[ \t]*\*[ \t]*{base}\b', source)}
    return found.pop() if len(found) == 1 else None


def variants(source, name):
    span = find(source, name)
    if not span or re.search(rf'\b{POINTER}\b', source):
        return []
    brace = source.find('{', span[0])
    clean = _blank(source)
    out = []
    for loop in _FOR.finditer(source, brace):
        open_at = loop.end() - 1
        end = close(clean, open_at, '{', '}')
        if end is None or end < 0:
            continue
        i, body = loop['i'], source[open_at:end]
        subscript = re.compile(rf'(?<![\w.>])(?P<base>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)?)\[[ \t]*{i}[ \t]*\]\.')
        bases = {m['base'] for m in subscript.finditer(body)}
        if len(bases) != 1:
            continue
        base = bases.pop()
        if re.search(rf'(?<![\w.>]){i}\b', subscript.sub('', body)):
            continue
        kind = _element_type(source, base)
        if not kind:
            continue
        walked = subscript.sub(f'{POINTER}->', body)
        header = (f"{loop['ind']}{POINTER} = &{base}[0];\n{loop['ind']}for ({loop['init']};{loop['cond']}; "
                  f"{loop['step']}, {POINTER}++) ")
        child = source[:loop.start()] + header + walked + source[end:]
        child = child[:brace + 1] + f'\n    {kind} *{POINTER};' + child[brace + 1:]
        out.append((FAMILY, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
