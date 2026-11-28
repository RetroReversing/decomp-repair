"""A stack record cleared by a fill call, whose members m2c declared as separate locals.

The game cleared a record (`memset(rows, 0, sizeof(rows))`, `bzero`) and then stored one or two of its members. m2c
sizes the array it declares for the record by the offsets the code indexes, and names each member stored directly as a
scalar of its own (`u8 sp10[0x8C]; s32 *sp98; s32 sp9C; ... memSet(sp10, 0, 0x98);`). Those scalars are never read, so
the compiler drops their stores, and the frame comes out short. The fill's own length says how big the record is: the
array is grown to it, and each local named inside that span becomes a member of the array, at its offset. One child
folds every filled array of the function (the members only pay off once the whole frame is right), then one per array.
Measured on an N64 function (SN GCC 2.8.1, three 0x98-byte tables on the stack): 2402 -> 660 as one child.

The second family moves a global's read above the fill call before it (`memSet(rows, 0, n); base = D_800F90E0;` as
`base = D_800F90E0; memSet(rows, 0, n);`): the game read it first, so it sits in a saved register across the call and
loads in the prologue. A fill of a local array cannot write the global, so the order is the same program. The same
function's last rows (220 -> 0 in the chain with the other two families).

The third family is the same for a fill whose destination m2c declared as a plain scalar, `f32 sp20; ... memSet(&sp20,
0, 0xC); sp20 = 20.0f;`: the other elements are never named, so the object is one word and every later stack slot is
out. The scalar becomes the array the fill's length says (`f32 sp20[3];`, `sp20[0] = 20.0f;`), and the words m2c named
inside the span become its elements. On an N64 sprite-drawing routine (SN GCC 2.8.1, two 12-byte vectors filled this
way) growing both took the draft from 8240 to 6905. Proposals only; the byte judge decides."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY_FOLD = 'fill_extent_locals'
FAMILY_HOIST = 'global_read_above_fill'
FAMILY_SCALAR = 'fill_extent_scalar'
FAMILIES = (FAMILY_FOLD, FAMILY_HOIST, FAMILY_SCALAR)
LIMIT = 8
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4, 's64': 8,
          'u64': 8, 'f64': 8, 'M2C_UNK': 4}
_FILL = re.compile(rf'(?<![\w.>])(?P<callee>\w*(?:[Mm]em[Ss]et|[Bb]zero)\w*)\s*\(\s*&?(?P<dest>{IDENT})\s*,'
                   rf'(?:\s*-?{NUMBER}\s*,)?\s*(?P<length>{NUMBER})\s*\)\s*;')
_ARRAY = re.compile(r'(?m)^[ \t]*(?P<type>u8|s8|char)\s+(?P<name>sp(?P<offset>[0-9A-Fa-f]+))\s*\[\s*'
                    r'(?P<count>0x[0-9A-Fa-f]+|\d+)\s*\]\s*;')
_SCALAR = re.compile(rf'(?m)^[ \t]*(?!return\b|goto\b)(?P<type>{IDENT})(?P<stars>(?:\s+|\s*\*+\s*))'
                     r'(?P<name>sp(?P<offset>[0-9A-Fa-f]+))'
                     r'\s*;[ \t]*\n')
_GLOBAL_READ = re.compile(rf'(?P<local>{IDENT})\s*=\s*(?P<symbol>D_[0-9A-Fa-f]{{8}})\s*;')


def _folds(part):
    """{array name: [(start, end, replacement)]} for each filled array with locals inside the fill's span."""
    clean = part.clean
    arrays = {m['name']: m for m in _ARRAY.finditer(clean, part.opening, part.end)}
    found = {}
    for call in _FILL.finditer(clean, part.opening, part.end):
        array = arrays.get(call['dest'])
        if not array or array['name'] in found:
            continue
        base, count = int(array['offset'], 16), int(array['count'], 0)
        length = int(call['length'].rstrip('uUlL'), 0)
        if not count < length <= 0x1000:
            continue
        # another array inside the span is a second object: the fill's length does not belong to this one then
        if any(base < int(a['offset'], 16) < base + length for a in arrays.values()):
            continue
        edits, members = [(*array.span('count'), f'0x{length:X}')], 0
        for scalar in _SCALAR.finditer(clean, part.opening, part.end):
            offset, stars = int(scalar['offset'], 16), scalar['stars'].count('*')
            size = 4 if stars else _SIZES.get(scalar['type'])
            if not base < offset < base + length:
                continue
            if size is None or offset + size > base + length:
                edits = None
                break
            kind = scalar['type'] + (' ' + '*' * stars if stars else '')
            member = f'(*({kind}{"*" if stars else " *"})&{array["name"]}[0x{offset - base:X}])'
            edits.append((scalar.start(), scalar.end(), ''))
            uses = re.compile(rf'(?<![\w.>]){scalar["name"]}\b')
            edits.extend((use.start(), use.end(), member)
                         for use in uses.finditer(clean, scalar.end(), part.end))
            members += 1
        if edits and members:
            found[array['name']] = edits
    return found


def _scalar_fills(part):
    """{scalar name: [(start, end, replacement)]} for each scalar local a fill writes more of than it declares."""
    clean = part.clean
    scalars = {m['name']: m for m in _SCALAR.finditer(clean, part.opening, part.end) if not m['stars'].count('*')}
    filled = {}
    for call in _FILL.finditer(clean, part.opening, part.end):
        scalar = scalars.get(call['dest'])
        size = _SIZES.get(scalar['type']) if scalar else None
        length = int(call['length'].rstrip('uUlL'), 0)
        if size and size < length <= 0x1000 and not length % size and '&' in call[0]:
            filled[call['dest']] = max(length, filled.get(call['dest'], 0))
    found = {}
    for name, length in filled.items():
        head = scalars[name]
        base, size = int(head['offset'], 16), _SIZES[head['type']]
        members = []
        for other, scalar in scalars.items():
            offset = int(scalar['offset'], 16)
            if base < offset < base + length:
                members.append((offset - base, other, scalar))
        # another filled object, or a member that is not one whole element, means the span is not one array
        if any(other in filled or _SIZES.get(scalar['type']) != size or at % size for at, other, scalar in members):
            continue
        edits = [(head.start(), head.end(), re.match(r'[ \t]*', head[0])[0]
                  + f'{head["type"]} {name}[{length // size}];\n')]
        edits += [(scalar.start(), scalar.end(), '') for _, _, scalar in members]
        whole = True
        for at, other, scalar in [(0, name, head), *members]:
            element = f'{name}[{at // size}]'
            kind = scalar['type']
            if kind != head['type']:
                element = f'(*({kind} *)&{element})'
            uses = re.compile(rf'(?<![\w.>])(?P<address>&\s*)?\b{other}\b(?P<next>\s*[\[.(])?')
            for use in uses.finditer(clean, part.opening, part.end):
                if any(start <= use.start() < end for start, end, _ in edits[:1 + len(members)]):
                    continue
                if use['next']:
                    whole = False
                    break
                start, address = use.start(), bool(use['address'])
                # `a & sp34` and `a && sp34` are not the address of the word
                if address and clean[:start].rstrip()[-1:] not in ('(', ',', '=', '?', ':', ';', '{'):
                    start, address = use.end('address'), False
                if address:
                    replacement = f'&{name}[{at // size}]' if at else name
                else:
                    replacement = element
                edits.append((start, use.end(), replacement))
        if not whole:
            continue
        found[name] = edits
    return found


def _hoists(source, part):
    clean = part.clean
    out = []
    local_arrays = {m['name'] for m in re.finditer(rf'(?m)^[ \t]*{IDENT}[\s*]+(?P<name>{IDENT})\s*\[[^\]]*\]\s*;',
                                                   clean[:part.end])}
    for call in _FILL.finditer(clean, part.opening, part.end):
        if call['dest'] not in local_arrays or clean[:call.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        read = _GLOBAL_READ.match(clean, call.end() + len(clean[call.end():]) - len(clean[call.end():].lstrip()))
        # a local named by its stack offset may lie in the filled record itself; an array symbol is an address, not a read
        if not read or re.fullmatch(r'sp[0-9A-Fa-f]+|D_\w+', read['local']) or re.search(
                rf'\b{read["symbol"]}\s*\[', clean) or re.search(rf'&\s*{read["local"]}\b', part.body):
            continue
        # the destination of the read must be a local of this function, not another global the callee could see
        if not re.search(rf'(?m)^[ \t]*(?!return\b|extern\b){IDENT}[\s*]+{read["local"]}\s*[;=]',
                         clean[part.opening:part.end]):
            continue
        line = source.rfind('\n', 0, call.start()) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        start = source.rfind('\n', 0, read.start()) + 1
        stop = source.find('\n', read.end()) + 1
        if source[start:read.start()].strip() or source[read.end():stop].strip() or start <= call.start():
            continue
        out.append(edit(source, [(line, line, indent + source[read.start():read.end()] + '\n'), (start, stop, '')]))
    return out


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    folds = _folds(part)
    out = []
    if folds:
        out.append((FAMILY_FOLD, edit(source, [item for edits in folds.values() for item in edits])))
        if len(folds) > 1:
            out.extend((FAMILY_FOLD, edit(source, edits)) for edits in folds.values())
    scalars = _scalar_fills(part)
    if scalars:
        out.append((FAMILY_SCALAR, edit(source, [item for edits in scalars.values() for item in edits])))
        if len(scalars) > 1:
            out.extend((FAMILY_SCALAR, edit(source, edits)) for edits in scalars.values())
    out.extend((FAMILY_HOIST, child) for child in _hoists(source, part))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',), 'order': 45}
