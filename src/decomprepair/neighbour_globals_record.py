"""Separate scalar globals that the target reaches from one another's address, declared as the members of one record.

On a 78-instruction N64 clamp routine (KMC GCC 2.7.2 `-O1 -G0 -mips3 -mgp32 -mfp32`) the target built one global's
address (`lui`/`addiu` into `$s0`) and stored two others through it (`sb $zero, -0x12($s0)`). The decompiler had named
each word its own symbol, and GCC cannot derive one extern's address from another's: with the symbols as members of
one record at the lowest address it did: 4406 -> 0 with this rewrite alone. The judge decides.

neighbour_globals_record
    The assembly forms `D_A`'s address and accesses `K($reg)` where `D_A + K` is another global `D_B`, both scalar
    integer or float globals the source declares itself (`extern s16 D_8021E1A2;`, named by their address, not in the
    project header). Every global so linked becomes a member of one record, declared under the lowest one's name, and
    each use reads the member. One child per linked group, and one with every group.

The program reads and writes the same bytes. A global whose declared size runs into the next one is left alone.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'neighbour_globals_record'
FAMILIES = (FAMILY,)
LIMIT = 4
SIZES = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
         'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'unsigned': 4, 'f32': 4, 'float': 4}

_EXTERN = re.compile(r'(?m)^[ \t]*extern[ \t]+(?P<type>(?:(?:un)?signed[ \t]+)?[A-Za-z_]\w*)[ \t]+'
                     r'(?P<name>D_(?P<address>[0-9A-Fa-f]{8}))[ \t]*;[ \t]*\n?')
_BASE = re.compile(r'\baddiu\s+(?P<reg>\$\w+),\s*(?P=reg),\s*%lo\(D_(?P<address>[0-9A-Fa-f]{8})\)')
_ACCESS = re.compile(r'\b(?:l[bh]u?|lw|lwc1|s[bhw]|swc1)\s+\$\w+,\s*(?P<offset>-?(?:0[xX][0-9a-fA-F]+|\d+))\((?P<reg>\$\w+)\)')
_WRITES = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?!s[bhwd]\b|swc1\b|sdc1\b|b|j|nop)[a-z][\w.]*\s+(?P<reg>\$\w+)\b')


def _links(asm):
    """(address, address) pairs the assembly reaches one from the other."""
    held, found = {}, set()
    for line in asm.splitlines():
        base = _BASE.search(line)
        if base:
            held[base['reg']] = int(base['address'], 16)
            continue
        access = _ACCESS.search(line)
        if access and access['reg'] in held:
            offset = int(access['offset'], 0)
            if offset:
                found.add((held[access['reg']], held[access['reg']] + offset))
        written = _WRITES.match(line)
        if written:
            held.pop(written['reg'], None)
    return found


def _groups(links, known):
    groups = []
    for pair in sorted(links):
        if not set(pair) <= set(known):
            continue
        joined = set(pair)
        for group in [g for g in groups if g & joined]:
            joined |= group
            groups.remove(group)
        groups.append(joined)
    return sorted(groups, key=min)


def _members(group, known):
    """The record's body, or None when a member's size runs into the next one."""
    lines, at, base = [], 0, min(group)
    for address in sorted(group):
        kind = ' '.join(known[address]['type'].split())
        offset = address - base
        if offset < at or offset % SIZES[kind]:
            return None
        if offset > at:
            lines.append(f'    u8 pad{at:X}[0x{offset - at:X}];')
        lines.append(f'    {kind} unk{offset:X};')
        at = offset + SIZES[kind]
    return '\n'.join(lines)


def _edits(source, part, group, known):
    base = known[min(group)]['name']
    body = _members(group, known)
    record = f'Record_{base}'
    if body is None or re.search(rf'\b{record}\b', source):
        return None
    edits = []
    first = min((known[address] for address in group), key=lambda hit: hit.start())
    for address in group:
        hit = known[address]
        text = f'typedef struct {{\n{body}\n}} {record};\nextern {record} {base};\n' if hit is first else ''
        edits.append((hit.start(), hit.end(), text))
        member = f'{base}.unk{address - min(group):X}'
        for use in re.finditer(rf'(?<![\w.>]){hit["name"]}\b', part.clean[:part.end]):
            if use.start() > part.opening:
                edits.append((use.start(), use.end(), member))
    return edits


def variants(source, name, header='', asm=''):
    part = view(source, name)
    if not part or not asm:
        return []
    known = {}
    for hit in _EXTERN.finditer(part.clean, 0, part.opening):
        glob = hit['name']
        if ' '.join(hit['type'].split()) not in SIZES or re.search(rf'\b{glob}\b', header):
            continue
        if len(re.findall(rf'(?m)^[ \t]*extern\b[^;\n]*\b{glob}\b', part.clean)) != 1:
            continue
        # a local or parameter of the same name would not be the global
        if re.search(rf'\b(?:[su](?:8|16|32)|f32|int|char|short)\s+\**\s*{glob}\b', part.clean[part.opening:part.end]):
            continue
        known[int(hit['address'], 16)] = hit
    # (a use in another function of the same source would be left naming a member the record replaced)
    known = {address: hit for address, hit in known.items()
             if not re.search(rf'\b{hit["name"]}\b', part.clean[:hit.start()] + part.clean[hit.end():part.opening]
                              + part.clean[part.end:])}
    groups = _groups(_links(asm), known)[:LIMIT]
    chosen = [(group, _edits(source, part, group, known)) for group in groups]
    chosen = [edits for _, edits in chosen if edits]
    out = [(FAMILY, edit(source, edits)) for edits in chosen]
    if len(chosen) > 1:
        out.append((FAMILY, edit(source, [item for edits in chosen for item in edits])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm')}
