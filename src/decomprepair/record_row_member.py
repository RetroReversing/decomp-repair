"""`*(T *)((char *)(base + i * S) + off)` written as a member of a record array inside the structure `base` points to.

m2c writes a field of the i-th fixed-size record in an owner structure as pointer arithmetic on the owner,
`*((f32 *) (((char *) (temp_s1 + (idx * 8))) + 0x200))`. GCC 2.7.2 expands that sum with the product first
(`addu $v0, $v0, $s1`), where the game's `owner->rec[idx].speed` (a COMPONENT_REF of an ARRAY_REF) puts the base first
(`addu $v0, $s1, $v0`): every spelling of the pointer arithmetic, and a byte-array member indexed the same way, compiled
to the product-first order; only a record with a real field of the access's type gave the target's. A
1300-instruction KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) controller routine had two such stores (an `s8` at
0x1FE and an `f32` at 0x200 in 8-byte records): 75 -> 65 with both. Read off the target's operand order, not the
compiler's source.

record_row_member
    For each owner local and record size S (a power of two up to 64) with sites `*((T *) (((char *) (B + (E * S))) + O))`
    whose fields fit in one record, a record typedef with each accessed field at its offset and an owner typedef that
    pads to the first record are declared before the function, and the sites become `((Owner *) B)->rec[E].fXX`. One
    child per owner and size, all its sites together."""
import re

from .csource import _blank, find

FAMILY = 'record_row_member'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'
_SIZE = {'u8': 1, 's8': 1, 'u16': 2, 's16': 2, 'u32': 4, 's32': 4, 'f32': 4}


def _expression_end(text, start):
    """End of the balanced parenthesised expression starting at `start` (which is '(')."""
    depth = 0
    for index in range(start, len(text)):
        depth += (text[index] == '(') - (text[index] == ')')
        if depth == 0:
            return index + 1
    return None


def _sites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    head = re.compile(rf'\*\s*\(\s*\(\s*(?P<t>{"|".join(_SIZE)})\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*(?P<b>{IDENT})\s*\+\s*(?=\()')
    out = []
    for hit in head.finditer(clean, span[0], span[1]):
        product = hit.end()
        stop = _expression_end(clean, product)
        if stop is None:
            continue
        m = re.fullmatch(r'\(\s*(?P<e>.+?)\s*\*\s*(?P<s>\d+)\s*\)', source[product:stop], re.S)
        if not m or int(m['s']) not in (2, 4, 8, 16, 32, 64):
            continue
        tail = re.compile(r'\s*\)\s*\)\s*\+\s*(?P<o>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\)').match(clean, stop)
        if not tail:
            continue
        out.append({'start': hit.start(), 'end': tail.end(), 't': hit['t'], 'b': hit['b'], 'e': m['e'].strip(),
                    's': int(m['s']), 'o': int(tail['o'], 0)})
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    groups = {}
    for site in _sites(source, name):
        groups.setdefault((site['b'], site['s']), []).append(site)
    out = []
    for (base, size), sites in groups.items():
        low = min(s['o'] for s in sites)
        high = max(s['o'] + _SIZE[s['t']] for s in sites)
        if high - low > size:
            continue
        widest = max(_SIZE[s['t']] for s in sites)
        first = high - size
        first += (-first) % widest  # the record aligned for its widest field
        if first > low or first < 0:
            continue
        fields = {}
        clash = False
        for s in sites:
            at = s['o'] - first
            if fields.get(at, s['t']) != s['t'] or any(o != at and o < at + _SIZE[s['t']] and at < o + _SIZE[t]
                                                       for o, t in fields.items()):
                clash = True
            fields[at] = s['t']
        if clash:
            continue
        record, owner = f'Row{size}_{base}', f'Rows{size}_{base}'
        lines, at = [], 0
        for offset in sorted(fields):
            if offset > at:
                lines.append(f'  u8 pad{at:X}[0x{offset - at:X}];')
            lines.append(f'  {fields[offset]} f{offset:X};')
            at = offset + _SIZE[fields[offset]]
        if at < size:
            lines.append(f'  u8 pad{at:X}[0x{size - at:X}];')
        typedefs = ('typedef struct\n{\n' + '\n'.join(lines) + f'\n}} {record};\n'
                    f'typedef struct\n{{\n  u8 head[0x{first:X}];\n  {record} rec[1];\n}} {owner};\n')
        child = source
        for s in sorted(sites, key=lambda s: -s['start']):
            child = child[:s['start']] + f"(({owner} *) {base})->rec[{s['e']}].f{s['o'] - first:X}" + child[s['end']:]
        start = find(child, name)[0]
        line = child.rfind('\n', 0, start) + 1
        out.append((FAMILY, child[:line] + typedefs + child[line:]))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
