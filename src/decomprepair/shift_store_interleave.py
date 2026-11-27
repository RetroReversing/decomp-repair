"""Two `field = value; field <<= k;` pairs rewritten so both stores of each halfword survive.

A scaled pair of texture coordinates written as

    v->s = st[0] * w; v->s <<= 6;
    v->t = st[1] * h; v->t <<= 6;

compiles to one store per field: GCC 2.8's flow pass deletes a store that is overwritten with nothing reading memory in
between. A target that stores the unshifted value and then the shifted one for both fields (`sh $v0; lwc1; mul.s; sll;
sh; trunc.w.s; mfc1; sh; sll; sh`) was written with the values held in locals and the first stores kept apart:

    a = st[0] * w; v->s = a; b = st[1] * h; v->t = b; v->s = a << 6; v->t = b << 6;

(a PSY-Q style SN GCC 2.8.1 N64 model loader, 780 -> exact with this step; evidence is that one function.) m2c writes the
pair with its own locals (`t = E; F = t; F = t << 6; u = G; H = u; H = u << 6;`), and the same order is offered by moving
the first shifted store past the second field's first store. Only `<<=`, `|=`, `&=` and `^=` with a number are touched, so
the fields are integers and the value held in an `int` keeps the same low bits; the right hand sides must not mention
either field.
"""
import re

from .csource import _blank, find

FAMILY = 'shift_store_interleave'
FAMILIES = (FAMILY,)

_LV = r'(?:[A-Za-z_]\w*(?:(?:->|\.)\w+|\[[^][;\n]*\])+)'
_PAIR = re.compile(
    rf'(?P<l1>{_LV})\s*=\s*(?P<e1>[^;=\n{{}}]+);(?P<g1>\s*)(?P=l1)\s*(?P<o1><<|\||&|\^)=\s*(?P<k1>\w+);(?P<g2>\s*)'
    rf'(?P<l2>{_LV})\s*=\s*(?P<e2>[^;=\n{{}}]+);(?P<g3>\s*)(?P=l2)\s*(?P<o2><<|\||&|\^)=\s*(?P<k2>\w+);')
_M2C = r'M2C_FIELD\([^;]*?\)'
_STORE = rf'(?:{_M2C}|{_LV})'
_CAST = r'(?:\([su]\d+\)\s*)?'
_M2C_PAIR = re.compile(
    rf'(?P<a>(?P<l1>{_STORE})\s*=\s*{_CAST}(?P<t1>[A-Za-z_]\w*);)(?P<g1>\s*)'
    rf'(?P<b>(?P=l1)\s*=\s*{_CAST}\(\s*(?P=t1)\s*<<\s*\w+\s*\);)(?P<mid>(?:\s*[A-Za-z_]\w*\s*=\s*[^;]+;){{0,4}}?)(?P<g2>\s*)'
    rf'(?P<c>(?P<l2>{_STORE})\s*=\s*{_CAST}(?P<t2>[A-Za-z_]\w*);)')


def _paired(match, names):
    first, second = names
    l1, l2 = match['l1'], match['l2']
    if l1 == l2 or any(lv in match[e] for lv in (l1, l2) for e in ('e1', 'e2')):
        return None
    for k in ('k1', 'k2'):
        if not re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?', match[k]):
            return None
    return (f"{first} = {match['e1'].strip()}; {l1} = {first}; {second} = {match['e2'].strip()}; {l2} = {second}; "
            f"{l1} = {first} {match['o1']} {match['k1']}; {l2} = {second} {match['o2']} {match['k2']};")


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    brace = source.find('{', span[0])
    clean = _blank(source)
    out = []
    names = ('repair_pair_a', 'repair_pair_b')
    sites = [(m, _paired(m, names)) for m in _PAIR.finditer(source) if clean[m.start()] != ' ']
    sites = [(m, text) for m, text in sites if text]
    if sites and not any(re.search(rf'\b{n}\b', source) for n in names):
        # every site at once (the pairs are usually copies of one macro), then the first alone
        for chosen in ([sites] if len(sites) == 1 else [sites, sites[:1]]):
            child = source
            for m, text in reversed(chosen):
                child = child[:m.start()] + text + child[m.end():]
            child = child[:brace + 1] + f"\n    int {names[0]};\n    int {names[1]};" + child[brace + 1:]
            out.append((FAMILY, child))
    moved = list(_M2C_PAIR.finditer(source))
    for chosen in ([moved, moved[:1]] if len(moved) > 1 else [moved] if moved else []):
        child = source
        for m in reversed(chosen):
            text = m['a'] + m['g1'] + m['mid'].lstrip() + m['g2'] + m['c'] + m['g2'] + m['b']
            child = child[:m.start()] + text + child[m.end():]
        if child != source:
            out.append((FAMILY, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
