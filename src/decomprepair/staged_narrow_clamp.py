"""A lower clamp of a loaded byte or halfword, staged through the clamped local with 16-bit types.

m2c reads `v = LOAD - 1; if (v < 0x41) v = 0x40;` as a temporary of its own (`t = LOAD - 1; v = t; if (t < 0x41)
{ v = 0x40; }`) with whatever widths it guessed. A target that loads into the clamped value's register, subtracts into
another, copies it back and tests the copy (`lbu $v1; addiu $v0,$v1,-1; move $v1,$v0; slti $v0,$v0,0x41; bnel; li
$v1,0x40`) kept two values apart:

    v = LOAD;
    t = v - 1;
    v = t;
    if (v < 0x41) { v = 0x40; }

with `v` a `s16` and `t` a `s16` or `u16`; the test reads `v`. Written with the load folded into the subtraction, or
with 8-bit or 32-bit locals, the compiler merges the two and drops the `move`. On a 117-instruction N64 function (SN GCC
2.8.1) this took the last 10 points to 0; each part alone is worse.

LOAD must be a signed or unsigned byte, or a signed halfword (a cast, or a member declared so), so that it and the
difference fit the new types. Offered for both the m2c form and the one-local form. A candidate; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view

FAMILY = 'staged_narrow_clamp'
FAMILIES = (FAMILY,)
_NARROW = r'(?:u8|s8|s16|unsigned\s+char|signed\s+char|char|short|signed\s+short)'
_HEAD = re.compile(
    rf'(?<![\w.>])(?P<t>{IDENT})\s*=\s*(?P<load>[^;{{}}=]+?)\s*-\s*(?P<step>{NUMBER})\s*;\s*'
    rf'(?:(?P<v>{IDENT})\s*=\s*(?P=t)\s*;\s*)?'
    rf'if\s*\(\s*(?P<tested>{IDENT})\s*(?P<op><=?)\s*(?P<bound>{NUMBER})\s*\)\s*'
    rf'(?:\{{\s*(?P<braced>{IDENT})\s*=\s*(?P<low>{NUMBER})\s*;\s*\}}|(?P<bare>{IDENT})\s*=\s*(?P<low2>{NUMBER})\s*;)')


def _narrow_load(load, text):
    load = load.strip()
    while load.startswith('(') and load.endswith(')'):
        load = load[1:-1].strip()
    if re.match(rf'\*\s*\(?\s*\(\s*{_NARROW}\s*\*\s*\)', load):
        return True
    member = re.search(rf'(?:->|\.)\s*({IDENT})$', load)
    return bool(member and re.search(rf'(?<![\w]){_NARROW}\s+{member[1]}\s*[;\[]', text))


def _declaration(clean, part, name):
    """The one plain integer declaration `TYPE name;` of a local, as a match, or None."""
    hits = list(re.finditer(rf'(?<![\w.>])(?P<type>{INTEGER})\s+{name}\s*;', clean[part.opening:part.end]))
    return hits[0] if len(hits) == 1 else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _HEAD.finditer(clean, part.opening + 1, part.end):
        temp, value = hit['t'], hit['v'] or hit['t']
        if (hit['braced'] or hit['bare']) != value or hit['tested'] not in (temp, value):
            continue
        load = source[hit.start('load'):hit.end('load')].strip()
        if not _narrow_load(load, clean + '\n' + header):
            continue
        low = hit['low'] or hit['low2']
        kept = _declaration(clean, part, value)
        other = _declaration(clean, part, temp) if temp != value else None
        if not kept or (temp != value and not other):
            continue
        stage = temp
        if temp == value:
            stage = 'repair_prior'
            if re.search(rf'\b{stage}\b', clean):
                continue
        for width in ('u16', 's16'):
            body = (f'{value} = {load};\n    {stage} = {value} - {hit["step"]};\n    {value} = {stage};\n'
                    f'    if ({value} {hit["op"]} {hit["bound"]}) {{ {value} = {low}; }}')
            edits = [(hit.start(), hit.end(), body)]
            start = part.opening
            declared = f's16 {value};'
            if other:
                edits.append((start + other.start(), start + other.end(), f'{width} {temp};'))
            else:
                declared += f' {width} {stage};'
            edits.append((start + kept.start(), start + kept.end(), declared))
            out.append((FAMILY, edit(source, sorted(edits))))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
