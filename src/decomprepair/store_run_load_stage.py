"""A field loaded at the end of a run of stores, read into a local ahead of the run (and the fence before it opened).

m2c writes the load where its value is stored, and a search often keeps the statement above the run in a one-shot
`do { } while (0)` wrapper:

    do { M2C_FIELD(p, s32 *, 0x80) = (s32) M2C_FIELD(a, s32 *, 0x80); } while (0);
    M2C_FIELD(p, s8 *, 0x7A) = 2;
    M2C_FIELD(p, s8 *, 0x74) = 2;
    M2C_FIELD(p, s16 *, 0x6A) = (s16) (M2C_FIELD(a, u16 *, 0x6A) - 2);

The game read the field first and stored after (`lhu; sb; sb; addiu; sh`), which the source says as
`temp_load = M2C_FIELD(a, u16 *, 0x6A);` above the run with `temp_load - 2` stored below it, the wrapper gone. Neither
edit helps alone: on the measured function the local with the wrapper kept scored the same (120) and the wrapper opened
without it scored worse (240). Measured on an SN64 GCC 2.8.1 (`-G0 -mips3 -O2 -mgas -mcpu=VR4300`) 81-instruction N64
object-spawning function with two such sites: 120 -> 60 per site, 0 with both.

The shape: in one block, `M2C_FIELD(P, ...) = value;` whose value reads exactly one `M2C_FIELD(A, T *, OFF)` of another
base `A` and calls nothing, preceded by a run of stores through `P` of names or numbers at other offsets than `OFF`.
One child per site and one with every site at once. The load may alias a store of the run, so each child is a candidate
for the judge to decide, not a proof.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view

FAMILY = 'store_run_load_stage'
FAMILIES = (FAMILY,)
LOCAL = 'temp_load'

FIELD = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<const>const\s+)?(?P<type>[su](?:8|16|32)|f32)\s*\*\s*,'
                   r'\s*(?P<off>0x[0-9A-Fa-f]+|\d+)\s*\)')
STORE = re.compile(rf'\A(?P<lhs>{FIELD.pattern})\s*=(?!=)\s*(?P<value>[^;{{}}]+);\Z', re.S)
PLAIN_VALUE = re.compile(rf'\A(?:\([su](?:8|16|32)\)\s*)?-?(?:{IDENT}|0x[0-9A-Fa-f]+|\d+(?:\.\d+)?f?)\Z')
FENCE = re.compile(r'\Ado\s*\{\s*(?P<body>[^{}]*;)\s*\}\s*while\s*\(\s*0\s*\)\s*;\Z', re.S)
CALL = re.compile(r'\b(?!M2C_FIELD\b)[A-Za-z_]\w*\s*\(|\+\+|--')


def _offset(text):
    return int(text, 0)


def _sites(source, part):
    """[(edits, local type)] for each store run that ends in a load of another base."""
    clean = part.clean
    sites = []
    for block_open, block_close in sorted(brace_pairs(clean, part.opening, part.end).items()):
        units = statements(clean, block_open + 1, block_close)
        stores = [STORE.match(clean[start:end]) for start, end in units]
        for index, store in enumerate(stores):
            if not store or CALL.search(store['value']):
                continue
            loads = list(FIELD.finditer(store['value']))
            if len(loads) != 1 or store['value'].count('M2C_FIELD') != 1:
                continue
            load = loads[0]
            if load['base'] == store['base']:
                continue
            first = index
            while first:
                earlier = stores[first - 1]
                if not (earlier and earlier['base'] == store['base'] and PLAIN_VALUE.match(earlier['value'].strip())
                        and _offset(earlier['off']) != _offset(load['off'])):
                    break
                first -= 1
            if first == index:
                continue
            start = units[first][0]
            line = source.rfind('\n', 0, start) + 1
            indent = re.match(r'[ \t]*', source[line:])[0]
            at = units[index][0] + store.start('value') + load.start()
            text = source[at:at + len(load[0])]
            edits = [(at, at + len(load[0]), LOCAL), (line, line, f'{indent}{LOCAL} = {text};\n')]
            if first:
                p, q = units[first - 1]
                fence = FENCE.match(clean[p:q])
                if fence and fence['body'].count(';') == 1:
                    edits.append((p, q, source[p + fence.start('body'):p + fence.end('body')]))
            sites.append((edits, load['type']))
    return sites


def variants(source, name):
    part = view(source, name)
    if not part or re.search(rf'\b{LOCAL}\w*\b', part.clean):
        return []
    sites = _sites(source, part)
    if not sites:
        return []
    nl = part.clean.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[nl:])[0] or '    '

    def child(chosen):
        # One local per loaded type: a second type gets a name of its own.
        types, edits = [], []
        for site_edits, kind in chosen:
            if kind not in types:
                types.append(kind)
            local = LOCAL if kind == types[0] else f'{LOCAL}_{kind}'
            edits += [(a, b, new.replace(LOCAL, local, 1) if LOCAL in new else new) for a, b, new in site_edits]
        declared = ''.join(f'{indent}{kind} {LOCAL if kind == types[0] else f"{LOCAL}_{kind}"};\n' for kind in types)
        return edit(source, edits + [(nl, nl, declared)])

    out = []
    if len(sites) > 1:
        out.append((FAMILY, child(sites)))
    out += [(FAMILY, child([site])) for site in sites]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
