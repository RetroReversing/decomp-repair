"""A pointer's step moved across the store beside it: `p++; *p = v;` and `p[1] = v; p++;` store the same bytes.

GCC 2.7.2 (KMC) keeps a second register for `p + 1` when every access to that address is `p[1]`: the loop pass reduces
it to a pointer of its own and increments both. A step written first (`p++; *p = v;`) leaves that address as the biv's
own and the target's second pointer never appears (measured: 1140 -> 0 on one 92-instruction character converter,
the one arm that stores a mark after its character). Offered both ways, one site at a time and all sites at once.
`v` must not name `p`, call, assign or step anything. At most 8 proposals; the judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'store_across_step'
FAMILIES = (FAMILY,)
LIMIT = 8

_VALUE = r'(?P<value>(?:(?!\+\+|--)[^;{}=\n])+)'
_STEP = r'(?:(?P=p)\+\+|\+\+(?P=p)|(?P=p)[ \t]*\+=[ \t]*1)'
_AFTER = re.compile(r'(?<![\w.>])(?P<p>[A-Za-z_]\w*)\[1\][ \t]*=[ \t]*' + _VALUE + r';(?P<gap>[ \t\n]*)' + _STEP + r';')
_PRE = re.compile(r'(?<![\w.>])(?:(?P<a>[A-Za-z_]\w*)(?:\+\+|[ \t]*\+=[ \t]*1)|\+\+(?P<b>[A-Za-z_]\w*));$')
_CALL = re.compile(r'\b(?!sizeof\b)[A-Za-z_]\w*[ \t]*\(')


def _safe(value, pointer):
    return not _CALL.search(value) and not re.search(rf'(?<![\w.>]){re.escape(pointer)}\b', value)


def _sites(source, clean, start, end):
    for hit in re.finditer(r'(?<![\w.>])(?:\+\+)?[A-Za-z_]\w*(?:\+\+|[ \t]*\+=[ \t]*1)?;[ \t\n]*\*[ \t]*[A-Za-z_]\w*[ \t]*=(?!=)[^;{}\n]*;', clean[:end]):
        if hit.start() <= start:
            continue
        step, store = hit.group(0).split(';', 1)
        first = _PRE.match(step + ';')
        left, _, value = store.rstrip(';').partition('=')
        pointer = first and (first['a'] or first['b'])
        value = value.strip()
        if not pointer or left.strip().lstrip('*').strip() != pointer or not _safe(value, pointer):
            continue
        gap = store[:len(store) - len(store.lstrip())]
        original = source[hit.start():hit.end()].split('=', 1)[1].rstrip(';').strip()
        yield hit.start(), hit.end(), f'{pointer}[1] = {original};{gap}{pointer}++;'
    for hit in _AFTER.finditer(clean, start + 1, end):
        pointer = hit['p']
        if _safe(hit['value'], pointer):
            value = source[hit.start('value'):hit.end('value')].strip()
            yield hit.start(), hit.end(), f"{pointer}++;{hit['gap']}*{pointer} = {value};"


def variants(source, name):
    """Proposals: one step moved across its store, then every such site together."""
    part = view(source, name)
    if not part:
        return []
    sites = list(_sites(source, part.clean, part.opening, part.end))
    out = [(FAMILY, edit(source, [site])) for site in sites]
    if len(sites) > 1:
        out.append((FAMILY, edit(source, sites)))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 97}  # the registry: no caller wiring (registry.py)
