"""A callee declared to return a word whose results are only ever kept in one 16- or 8-bit local.

    s32 spawn(...);  ...  u16 e;  e = spawn(...);  if ((u16) (e + 2) >= 2) ...

Under KMC GCC 2.7.2 at -O1 the caller's later reads of such a local tell the two declarations apart: with the callee
declared `u16` the target copies the result (`move $s1, $v0`) and then computes from the copy (`addiu $v0, $s1, 2`);
declared `s32` the computation reads `$v0` itself, one register row from the match (a 345-instruction function).
`wide_return_prototype` handles the 64-bit case; this is the narrow one. Offered when every result of the callee is
kept in a local of one narrow type, or dropped, so the caller's behaviour is unchanged. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'callee_narrow_return'
FAMILIES = (FAMILY,)
_PROTOTYPE = re.compile(
    rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>s32|u32|int|unsigned(?:[ \t]+int)?)'
    rf'[ \t]+(?P<f>{IDENT})[ \t]*\((?P<args>[^;{{}}]*)\)[ \t]*;')
_NARROW = r'(?:u16|s16|u8|s8)'


def _narrow_local(body, var):
    hit = re.search(rf'(?<![\w.])(?P<t>{_NARROW})[ \t]+{re.escape(var)}[ \t]*(?:;|=|,)', body)
    return hit['t'] if hit else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    out = []
    for proto in _PROTOTYPE.finditer(clean[:part.opening]):
        f = proto['f']
        if f == name:
            continue
        kinds = set()
        ok = True
        for call in re.finditer(rf'(?<![\w.>]){re.escape(f)}\s*(?P<open>\()?', body):
            if not call['open']:
                ok = False  # the callee's address is used: its type is part of that use
                break
            before = body[:call.start()].rstrip()
            if before[-1:] in (';', '{', '}'):
                continue  # the result is dropped
            assign = re.search(rf'(?:^|[;{{}}\s])({IDENT})\s*=\s*$', before)
            kind = assign and _narrow_local(body, assign[1])
            if not kind:
                ok = False
                break
            kinds.add(kind)
        if ok and len(kinds) == 1:
            out.append((FAMILY, edit(source, [(proto.start('type'), proto.end('type'), kinds.pop())])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
