"""Two m2c spellings of values cse already shares, written back so cse shares them the way the game's code did.

Found matching a 1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller routine (420 -> 125 in the
isolated judge with the other steps of that stretch; these two: 290 -> 180 and 180 -> 125).

product_local_inline
    m2c names the products a block computes from one index (`temp_a3 = idx * 8; temp_a1_2 = idx * 0xE8;`) after the
    registers they ended in. GCC expands `idx * 0xE8` as shifts and adds whose first step is `idx << 3`, and cse then
    uses one register for that step and for `idx * 8`; when `idx * 8` is a user variable of its own, cse keeps the older
    temporary and the variable becomes a `move` from it (the target computed `sll $a3, $v0, 3` straight into the
    register the later arm reads). Written at each use (`base + idx * 8`), the product is cse's own value and no copy is
    made. Each local `V = E * K;` (E a plain name, K an integer literal; V set once, E not written before V's last use)
    is offered inlined alone, and all of them together first.

loaded_field_compound
    `v = *(T *)(p + off); ... *(T *)(p + off) = (T)(v + d);` written as `*(T *)(p + off) += d;`: the add reads the field
    again (cse gives it the loaded value back), and the store no longer reads `v` in the narrow width m2c's cast gives
    it, which in the routine above was a stale QI pseudo of its own and the 8-byte frame slot the target has. The
    load stays (v is read elsewhere); p and v must not be written between.

Hypotheses read off `-dl -dg` dumps of the one routine, not confirmed in the compiler's source. The exact judge decides."""
import re

from .csource import _blank, find

FAMILY_PRODUCT = 'product_local_inline'
FAMILY_FIELD = 'loaded_field_compound'
FAMILIES = (FAMILY_PRODUCT, FAMILY_FIELD)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'


def _span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    head = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[span[0]:span[1]])
    return (span[0] + head.end() - 1, span[1]) if head else None


def _mention(name):
    return re.compile(rf'(?<![\w.>]){re.escape(name)}\b')


def _written(name, text):
    return bool(re.search(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text)
                or re.search(rf'(?:\+\+|--)\s*{re.escape(name)}\b|\b{re.escape(name)}\s*(?:\+\+|--)|&\s*{re.escape(name)}\b', text))


def _declaration(var):
    return re.compile(rf'^[ \t]*(?:[su](?:8|16|32)|int|unsigned int|short|char)[ \t]+{re.escape(var)}[ \t]*;[ \t]*\n', re.M)


def _products(source, name):
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[span[0]:span[1]]
    out = []
    pattern = re.compile(rf'^(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<e>{IDENT})\s*\*\s*(?P<k>{NUMBER})\s*;[ \t]*\n', re.M)
    for hit in pattern.finditer(clean, span[0], span[1]):
        var, e = hit['var'], hit['e']
        if var == e or not _declaration(var).search(body):
            continue
        mention = _mention(var)
        sets = re.findall(rf'(?<![\w.>]){re.escape(var)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', body)
        if len(sets) != 1 or re.search(rf'&\s*{re.escape(var)}\b', body):
            continue
        uses = [m.start() for m in mention.finditer(clean, hit.end(), span[1])]
        if not uses:
            continue
        if _written(e, clean[hit.end():uses[-1]]):
            continue
        out.append((hit, uses, f'({e} * {hit["k"]})'))
    return out


def _inline(source, sites, name):
    edits = []
    for hit, uses, text in sites:
        edits.append((hit.start(), hit.end(), ''))
        for at in uses:
            edits.append((at, at + len(hit['var']), text))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    span = _span(source, name)
    for hit, _, _ in sites:
        var = hit['var']
        if span and len(_mention(var).findall(_blank(source), span[0], span[1])) == 1:
            source = _declaration(var).sub('', source, count=1)
            span = _span(source, name)
    return source


FIELD = r'\*\s*\(\s*\(\s*(?P<t>[su](?:8|16|32))\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P<p>{p})\s*\)\s*\+\s*(?P<o>{n})\s*\)\s*\)'


def _fields(source, name):
    span = _span(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    load = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*' + FIELD.format(p=IDENT, n=NUMBER) + r'\s*;')
    for hit in load.finditer(clean, span[0], span[1]):
        v, t, p, o = hit['v'], hit['t'], hit['p'], hit['o']
        field = FIELD.format(p=re.escape(p), n=re.escape(o)).replace('(?P<t>[su](?:8|16|32))', re.escape(t))
        store = re.compile(field.replace('(?P<p>', '(?:').replace('(?P<o>', '(?:') +
                           rf'\s*=\s*\(\s*{re.escape(t)}\s*\)\s*\(\s*{re.escape(v)}\s*\+\s*(?P<d>{IDENT}|{NUMBER})\s*\)\s*;')
        m = store.search(clean, hit.end(), span[1])
        if not m:
            continue
        between = clean[hit.end():m.start()]
        if _written(p, between) or _written(v, between) or m['d'] in (v, p):
            continue
        if re.search(field.replace('(?P<p>', '(?:').replace('(?P<o>', '(?:') + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', between):
            continue
        text = source[m.start():m.end()]
        lhs = text[:text.index('=')].rstrip()
        out.append((m.start(), m.end(), f'{lhs} += {m["d"]};'))
    return out


def variants(source, name):
    out = []
    sites = _products(source, name)
    if len(sites) > 1:
        out.append((FAMILY_PRODUCT, _inline(source, sites, name)))
    for site in sites:
        out.append((FAMILY_PRODUCT, _inline(source, [site], name)))
    for start, end, text in _fields(source, name):
        out.append((FAMILY_FIELD, source[:start] + text + source[end:]))
    seen, unique = set(), []
    for family, child in out:
        if child != source and child not in seen:
            seen.add(child)
            unique.append((family, child))
    return unique[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
