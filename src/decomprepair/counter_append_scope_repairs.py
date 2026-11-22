"""An append to two parallel tables through a global counter, with one scaled index and the counter read once for the bump.

m2c writes the registration of an entry in two tables that share a counter as the first table's element field, the
scaled counter that indexes the second, the second store and, after the block, the increment:

    ARR1[G].f = v1; OFF = G * N;
    *((T *) (ARR2 + OFF)) = v2;
    G += 1;

The target computes `G * N` once and uses the register for both stores' addresses (`lui $at; addu $at,$at,$v1` twice),
reads `G` again into a different register for the bump (`lbu $v0; ... addiu $v0,$v0,1; sb`), and does the bump
beside the second store, where the second scheduler leaves the reload ahead of the store. That is, in source: the
first store through the same scaled index, a local that holds the counter for the second half, and the increment
written from that local at the end of the scope the stores sit in:

    OFF = G * N; *((s8 *)((char *) ARR1 + OFF)) = v1;
    CNT = G; *((T *) (ARR2 + OFF)) = v2; G = CNT + 1;

None of the three changes helps alone (1336, 1110 and 1086 against 1110); together they scored 1041 on a 180-instruction
N64 function, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`. The first table must be an `extern` array of a typedef'd
struct whose first member is `f`, so that its element field is the scalar at the element's address. The counter is a
plain global. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILIES = ('counter_append_scope',)
LIMIT = 4
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
NAME = '__repair_append_count'
OFFSET = '__repair_append_offset'
SHAPE = re.compile(
    rf'(?P<s1>(?P<arr1>{IDENT})\s*\[\s*(?P<g>{IDENT})\s*\]\s*\.\s*(?P<f>{IDENT})\s*=\s*(?P<v1>[^;]+);)'
    rf'(?P<gap1>\s*)(?P<s2>(?P<off>{IDENT})\s*=\s*(?P=g)\s*\*\s*(?P<n>{NUM})\s*;)'
    rf'(?P<gap2>\s*)(?P<s3>\*\s*\(\(\s*(?P<t2>[^()]+?)\s*\)\s*\(\s*(?P<arr2>{IDENT})\s*\+\s*(?P=off)\s*\)\s*\)\s*=\s*(?P<v2>[^;]+);)'
    rf'(?P<close>(?:\s*\}}\s*while\s*\(\s*0\s*\)\s*;)?)'
    rf'(?P<gap3>\s*)(?P<s4>(?P=g)\s*(?:\+=\s*1|\+\+)\s*;)')


def _first_member(clean, arr, field):
    """The scalar type of `field` when it is the first member of the struct `extern T arr[];` is an array of."""
    decl = re.search(rf'extern\s+(?P<t>{IDENT})\s+{re.escape(arr)}\s*\[\s*\]\s*;', clean)
    if not decl:
        return None
    struct = re.search(rf'typedef\s+struct\s*(?:{IDENT})?\s*\{{\s*(?P<type>[A-Za-z_][\w ]*?)\s+{re.escape(field)}\s*;[^}}]*\}}\s*{re.escape(decl["t"])}\s*;', clean)
    if not struct or '*' in struct['type']:
        return None
    return struct['type']


def variants(source, name, header=''):
    part = view(source, name)
    if not part or NAME in part.clean or OFFSET in part.clean:
        return []
    out = []
    for m in SHAPE.finditer(part.clean, part.opening, part.end):
        scalar = _first_member(part.clean, m['arr1'], m['f'])
        g = m['g']
        if not scalar or m['off'] == g or re.search(rf'\b{re.escape(g)}\b', m['v1'] + ' ' + m['v2']):
            continue
        if re.search(rf'\b{re.escape(m["off"])}\b', part.clean[m.end():part.end]):
            continue
        indent = re.match(r'[ \t]*', part.clean[part.clean.rfind('\n', 0, m.start('s1'))+1:m.start('s1')])[0]
        first = f'{OFFSET} = {g} * {m["n"]}; *(({scalar} *) ((char *) {m["arr1"]} + {OFFSET})) = {m["v1"].strip()};'
        third = re.sub(rf'\+\s*{re.escape(m["off"])}\b', '+ ' + OFFSET, m['s3'], count=1)
        second = f'\n{indent}{NAME} = {g};\n{indent}{third}\n{indent}{g} = {NAME} + 1;'
        closing = m['close']
        text = edit(source, [
            (part.opening+1, part.opening+1, f'\n  s32 {NAME};\n  s32 {OFFSET};'),
            (m.start('s1'), m.end(), first + second + closing + ''),
        ])
        out.append(text)
    return [(FAMILIES[0], c) for c in out[:LIMIT] if c != source]
