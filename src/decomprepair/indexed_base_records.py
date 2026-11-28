"""Accesses `M2C_FIELD(base, T *, i * STRIDE + k)` off one object, written as members of a record array.

Once a loop's stepped pointer is written as its counter's index (`pointer_walk_to_index`), m2c's draft reads one object
three ways: a pointer local that holds its address, byte offsets with the stride in them, and constant offsets off the
address itself:

    p = &gSlots;                                           ((Row *) &gSlots)[i].m0 = 0;
    M2C_FIELD(p, s32 *, i * 0x10) = 0;            ->       ((Row *) &gSlots)[i].mC = 0;
    M2C_FIELD(p, s8 *, i * 0x10 + 0xC) = 0;                ...
    M2C_FIELD(&gSlots, s8 *, 0x4C) = 1;                    ((Row *) &gSlots)[4].mC = 1;

The game declared an array of records. Written as members, the compiler makes one induction pointer of its own for the
loop, keeps one address register for the object across the whole function and orders the stores as member stores; the
casts with a pointer local give it other registers. The same shape reads a stack copy of a table (`&sp10`).

`global_offset_records` reads `&D + offset` sums and `indexed_symbol_records` address-named tables; neither takes the
`M2C_FIELD` offset form. An object is rewritten only when every pointer local that holds its address is set to nothing
else and used in nothing but those accesses, every indexed access has the same stride, each member offset has one type
and no two members overlap. One child with every such object, one per object, and the same with a global declared as the
array itself. A loader on SN GCC 2.8.1 (`-G0 -mips3 -O2`) went from 1450 to a match's shape with it. The judge decides.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'indexed_base_records'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4, 'M2C_UNK': 4}
_FIELD = re.compile(rf'\bM2C_FIELD\(\s*(?P<base>&\s*{_ID}|{_ID})\s*,\s*(?P<type>{_ID})\s*(?P<stars>\*+)\s*,')
_TERM = re.compile(rf'(?P<index>{_ID}|\(\s*{_ID}\s*[-+]\s*1\s*\))\s*\*\s*(?P<stride>{_NUM})(?:\s*\+\s*(?P<k>{_NUM}))?')
LIMIT = 6


def _accesses(clean, opening, end):
    """[(start, end, base, member type, size, index or None, stride or None, offset)] of every readable access."""
    found = []
    for hit in _FIELD.finditer(clean, opening, end):
        paren = clean.index('(', hit.start())
        stop = close(clean, paren, '(', ')')
        if stop < 0:
            continue
        after = stop + 1
        offset = clean[hit.end():stop].strip()
        member = 'void *' if len(hit['stars']) > 1 else hit['type']
        size = 4 if len(hit['stars']) > 1 else _SIZES.get(hit['type'])
        if size is None:
            continue
        base = re.sub(r'\s', '', hit['base'])
        if re.fullmatch(_NUM, offset):
            found.append((hit.start(), after, base, member, size, None, None, int(offset, 0)))
        elif term := _TERM.fullmatch(offset):
            index = term['index'][1:-1].strip() if term['index'].startswith('(') else term['index']
            found.append((hit.start(), after, base, member, size, index, int(term['stride'], 0),
                          int(term['k'] or '0', 0)))
        else:
            found.append((hit.start(), after, base, member, size, False, None, None))
    return found


def _aliases(clean, opening, end, accesses):
    """{pointer local: (object, [spans of its sets and declaration])} for locals only set to `&object` and only used
    as the base of an access."""
    out = {}
    for name in dict.fromkeys(a[2] for a in accesses if not a[2].startswith('&')):
        sets = list(re.finditer(rf'(?m)^[ \t]*{name}[ \t]*=[ \t]*&[ \t]*({_ID})[ \t]*;[ \t]*\n', clean[opening:end]))
        declared = re.search(rf'(?m)^[ \t]*{_ID}[ \t]*\*[ \t]*{name}[ \t]*;[ \t]*\n', clean[opening:end])
        if not sets or not declared or len({s[1] for s in sets}) != 1:
            continue
        uses = len(re.findall(rf'(?<![\w.>]){name}\b', clean[opening:end]))
        if uses != len(sets) + 1 + sum(a[2] == name for a in accesses):
            continue
        out[name] = (sets[0][1], [(opening + s.start(), opening + s.end()) for s in (*sets, declared)])
    return out


def _plan(clean, opening, end):
    """{object: (stride, {offset: (type, size)}, [(start, end, index, offset)], [spans to drop])}"""
    accesses = _accesses(clean, opening, end)
    aliases = _aliases(clean, opening, end, accesses)
    grouped = {}
    for access in accesses:
        base = access[2]
        target = base[1:] if base.startswith('&') else aliases[base][0] if base in aliases else None
        if target:
            grouped.setdefault(target, []).append(access)
    plan = {}
    for target, group in grouped.items():
        strides = {a[6] for a in group if a[6] is not None}
        if len(strides) != 1 or any(a[5] is False for a in group):
            continue
        stride = strides.pop()
        # a pointer to the same object the accesses don't go through would keep the casts' view of it
        if any(info[0] == target and name not in {a[2] for a in group} for name, info in aliases.items()):
            continue
        members, rewrites, good = {}, [], True
        for start, stop, _base, member, size, index, _stride, offset in group:
            if index is None:
                index, offset = str(offset // stride), offset % stride
            good = good and offset + size <= stride and offset % size == 0
            kind = members.setdefault(offset, (member, size))
            good = good and kind[1] == size
            rewrites.append((start, stop, index, offset, member))
        ordered = sorted(members.items())
        if not good or any(a + s > b for (a, (_t, s)), (b, _m) in zip(ordered, ordered[1:])):
            continue
        drop = [span for name, info in aliases.items() if info[0] == target for span in info[1]]
        plan[target] = (stride, dict(ordered), rewrites, drop)
    return plan


def _record(tag, members, stride):
    lines, at = [], 0
    for offset, (member, size) in members.items():
        if offset > at:
            lines.append(f'    char pad{at:X}[0x{offset - at:X}];')
        space = '' if member.endswith('*') else ' '
        lines.append(f'    {member}{space}m{offset:X};')
        at = offset + size
    if stride > at:
        lines.append(f'    char pad{at:X}[0x{stride - at:X}];')
    return 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\n'


def _block_local(source, clean, opening, end, target):
    """(span of the local's type, bytes) when `target` is a local block of one array: `Block target;`."""
    declared = re.search(rf'(?m)^[ \t]*(?P<type>{_ID})[ \t]+{target}[ \t]*;[ \t]*\n', clean[opening:end])
    if not declared:
        return None
    block = re.search(rf'typedef[ \t]+struct[ \t]*\{{[ \t]*(?P<member>{_ID})[ \t]+{_ID}\[(?P<n>{_NUM})\];[ \t]*\}}[ \t]*'
                      rf'{declared["type"]}[ \t]*;', source)
    if not block or block['member'] not in _SIZES:
        return None
    at = opening + declared.start('type')
    return (at, opening + declared.end('type')), int(block['n'], 0) * _SIZES[block['member']]


def _apply(source, span, plan, chosen, declare):
    edits, typedefs, arrays = [], [], []
    for number, target in enumerate(chosen):
        stride, members, rewrites, drop = plan[target]
        tag = f'__repair_row_{target}'
        typedefs.append(_record(tag, members, stride))
        extern = re.search(rf'(?m)^extern[ \t]+{_ID}[ \t]+{target}[ \t]*;[ \t]*\n', source[:span[0]])
        if declare and extern:
            arrays.append(target)
            edits.append((extern.start(), extern.end(), ''))
        rows = target if target in arrays else f'(({tag} *) &{target})'
        local = _block_local(source, _blank(source), span[3], span[1], target)
        if local and local[1] % stride == 0:
            # a stack copy of a table is the table: a record of the rows, so each local keeps its own induction pointer
            typedefs.append(f'typedef struct {{ {tag} e[0x{local[1] // stride:X}]; }} {tag}_table;\n')
            edits.append((*local[0], f'{tag}_table'))
            rows = f'{target}.e'
        for start, stop, index, offset, member in rewrites:
            text = f'{rows}[{index}].m{offset:X}'
            # one word read as an integer in one place and as a pointer in another is one member: a cast through the
            # member's address would hide it from the compiler again
            if member != members[offset][0] and 'f32' in (member, members[offset][0]):
                text = f'*({member} *) &{text}'
            edits.append((start, stop, text))
        edits += [(a, b, '') for a, b in drop]
    text = source
    ordered = sorted(edits)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        return None
    for a, b, new in reversed(ordered):
        text = text[:a] + new + text[b:]
    head = re.search(rf'(?m)^[^\n;]*\b{re.escape(span[2])}\s*\([^;{{}}]*\)\s*\{{', _blank(text))
    if not head:
        return None
    for target in chosen:
        if target in arrays:
            # the address of the array is the array
            text = re.sub(rf'&\s*{target}\b(?!\s*\[)', target, text)
    head = re.search(rf'(?m)^[^\n;]*\b{re.escape(span[2])}\s*\([^;{{}}]*\)\s*\{{', _blank(text))
    declarations = ''.join(typedefs) + ''.join(f'extern __repair_row_{t} {t}[];\n' for t in arrays)
    return text[:head.start()] + declarations + text[head.start():]


def variants(source, name):
    """Proposals: each object indexed through byte offsets, written as an array of records."""
    span = find(source, name)
    if not span or 'M2C_FIELD(' not in source or '__repair_row_' in source:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    plan = _plan(clean, opening, span[1])
    if not plan:
        return []
    span = (span[0], span[1], name, opening)
    targets = list(plan)
    choices = [targets] + ([[t] for t in targets] if len(targets) > 1 else [])
    out = []
    for declare in (True, False):
        for chosen in choices:
            text = _apply(source, span, plan, chosen, declare)
            if text and text not in [t for _f, t in out]:
                out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
