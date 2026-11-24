"""Consecutive elements of a frame array stored one by one through a pointer, as the struct copy the game made.

`*(Plane *) out = *(Plane *) &plane;` compiles to word loads and stores (`lw $v0, 0xf8($sp)` ... `sw $v0, ($t4)`),
grouped four loads then four stores. m2c writes it as one float store per element,

    ((Field_f32 *) (((char *) arg7) + 0))->v = spF8;      /* or M2C_FIELD(arg7, f32 *, 0) = spF8; */
    ((Field_f32 *) (((char *) arg7) + 4))->v = spFC;
    ...

which gcc 2.7.2 compiles to `lwc1`/`swc1` pairs, one register, interleaved. When the stored values are consecutive
elements of one frame array (`#define spFC stack_spF8[1]`, or `a[1]` written out) and the destination offsets step by
the element size, the run is a block copy: written as an assignment of a one-member struct of that many elements, the
target's word copy comes back. A 1928-instruction collision sweep (KMC gcc 2.7.2) copied a four-float plane to an
out-parameter that way: 18477 -> 17437 from this edit alone. The struct's name is new; the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'frame_array_block_copy'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
SIZES = {'f32': 4, 's32': 4, 'u32': 4, 'float': 4, 'int': 4}
# ((Field_f32 *) (((char *) P) + OFF))->v = X;   or   M2C_FIELD(P, f32 *, OFF) = X;
STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)(?:\(\s*\(\s*Field_(?P<t1>\w+)\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*'
                   r'(?P<p1>' + I + r')\s*\)\s*\+\s*(?P<o1>' + NUM + r')\s*\)\s*\)\s*->\s*v|M2C_FIELD\(\s*(?P<p2>' + I +
                   r')\s*,\s*(?P<t2>\w+)\s*\*\s*,\s*(?P<o2>' + NUM + r')\s*\))\s*=\s*(?:\(\s*\w+\s*\)\s*)?'
                   r'(?P<x>' + I + r'(?:\s*\[\s*\d+\s*\])?)\s*;[ \t]*\n')


def _element(source, value):
    """(array, index) of a value: `a[2]`, or a name `#define`d as one."""
    m = re.fullmatch(r'(' + I + r')\s*\[\s*(\d+)\s*\]', value)
    if m:
        return m[1], int(m[2])
    d = re.search(r'(?m)^#define\s+' + re.escape(value) + r'\s+(' + I + r')\s*\[\s*(\d+)\s*\]\s*$', source)
    return (d[1], int(d[2])) if d else None


def _runs(source, start, end):
    stores = []
    for m in STORE.finditer(source, start, end):
        kind = m['t1'] or m['t2']
        if kind not in SIZES:
            continue
        stores.append((m, m['p1'] or m['p2'], int(m['o1'] or m['o2'], 0), kind, _element(source, m['x'])))
    runs, run = [], []
    for item in stores:
        m, ptr, off, kind, el = item
        prev = run[-1] if run else None
        if (prev and el and prev[4] and prev[0].end() == m.start() and ptr == prev[1] and kind == prev[3]
                and off == prev[2] + SIZES[kind] and el[0] == prev[4][0] and el[1] == prev[4][1] + 1):
            run.append(item)
            continue
        if len(run) >= 2:
            runs.append(run)
        run = [item] if el else []
    if len(run) >= 2:
        runs.append(run)
    return runs


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    out = []
    for run in _runs(source, opening, span[1])[:6]:
        first = run[0]
        kind, n = first[3], len(run)
        block = 'Block%d_%s' % (n, kind)
        ptr, off = first[1], first[2]
        array, index = first[4]
        dest = '(%s *) %s' % (block, ptr) if off == 0 else '(%s *) (((char *) %s) + 0x%X)' % (block, ptr, off)
        line = '%s*(%s) = *((%s *) (&%s[%d]));\n' % (first[0]['indent'], dest, block, array, index)
        text = source[:first[0].start()] + line + source[run[-1][0].end():]
        if not re.search(r'\b' + block + r'\b', source):
            text = text[:span[0]] + 'typedef struct { %s v[%d]; } %s;\n' % (kind, n, block) + text[span[0]:]
        out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
