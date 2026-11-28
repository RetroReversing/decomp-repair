"""A compound update through a local copy of a pointer member, written through the member again.

m2c names a pointer it loaded once and writes every later access through the name:

    temp = M2C_FIELD(self, Part **, 0x48);
    if (temp != NULL) {
        ...                                                     ...
        M2C_FIELD(temp, s32 *, 0x1C) =              ->          M2C_FIELD(M2C_FIELD(self, Part **, 0x48), s32 *, 0x1C)
            (s32) (M2C_FIELD(temp, s32 *, 0x1C) + 0x100);           += 0x100;

The game wrote `self->part->angle += 0x100`: after stores through `self` the compiler reads the member again, finds
the value it still holds and copies it (`move $v1, $a1`), then loads and stores through the copy. A source that keeps
the first name has one register where the target has two. On a 229-instruction SN GCC 2.8.1 N64 pickup update this was
part of a chain to exact: with this step left out the rest stood at 110.

Offered for a local assigned once from a member read (`M2C_FIELD(p, T **, K)` or `p->m`), `p` not assigned in the
function, for each `+=`-shaped update through the local. The judge decides; the family says nothing about whether a
store in between could have changed the member.
"""
import re

from .csource import _blank, find

FAMILY = 'member_update_reread'
FAMILIES = (FAMILY,)
LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
TYPE = r'[A-Za-z_][\w ]*?\**\s*\*'
_LOAD = re.compile(r'(?<![\w.>])(?P<local>' + IDENT + r') = (?P<load>M2C_FIELD\((?P<base>' + IDENT + r'), ' + TYPE
                   + r', \w+\)|(?P<arrow>' + IDENT + r')->' + IDENT + r');')


def _updates(clean, local):
    """(start, end, place, operator, value) of each statement that reads a place through `local` and stores it back."""
    place = r'(?P<place>M2C_FIELD\(' + local + r', ' + TYPE + r', \w+\)|' + local + r'->' + IDENT + r')'
    op = r'(?P<op>[-+&|^])'
    value = r'(?P<value>-?(?:0[xX][0-9a-fA-F]+|\d+))'
    long = re.compile(r'(?<=[;{}\n])[ \t]*' + place + r' = (?:\(\w+\) )?\((?P=place) ' + op + ' ' + value + r'\);')
    short = re.compile(r'(?<=[;{}\n])[ \t]*' + place + ' ' + op + '= ' + value + ';')
    for pattern in (long, short):
        for hit in pattern.finditer(clean):
            yield hit.start('place'), hit.end(), hit['place'], hit['op'], hit['value']


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean.find('{', span[0], span[1])
    if body < 0:
        return []
    result = []
    for load in _LOAD.finditer(clean, body, span[1]):
        local, base = load['local'], load['base'] or load['arrow']
        assigned = r'(?<![\w.>])%s\s*(?:(?:[-+*/%%&|^]|<<|>>)?=(?!=)|\+\+|--)'
        if local == base or len(re.findall(assigned % local, clean[body:span[1]])) != 1 \
                or re.search(assigned % base, clean[body:span[1]]):
            continue
        member = source[load.start('load'):load.end('load')]
        for start, end, place, op, value in _updates(clean[:span[1]], local):
            if start < load.end():
                continue
            through = (place.replace(f'M2C_FIELD({local}, ', f'M2C_FIELD({member}, ', 1) if place.startswith('M2C_FIELD')
                       else member + place[len(local):])
            result.append((FAMILY, source[:start] + f'{through} {op}= {value};' + source[end:]))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
