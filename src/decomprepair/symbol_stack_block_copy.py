"""m2c's copy of a constant block into separate stack words, halves and bytes, written back as one block copy.

`char name[32]; strcpy(name, "X.PAK");` (or a `memcpy` from read-only data, in each arm of an `if`) compiles to a GCC
block move: the symbol's address in one register, whole words through three temporaries, then the half and byte tail.
m2c has no array there, so it declares one local per stack offset it saw and copies each at its own width:

    s32 sp20[2];
    s16 sp28;
    s8 sp2A;
    ...
    sp20[0] = M2C_FIELD(&D_X, s32 *, 0);
    sp20[1] = M2C_FIELD(&D_X, s32 *, 4);
    sp28 = M2C_FIELD(&D_X, s16 *, 8);
    sp2A = M2C_FIELD(&D_X, s8 *, 0xA);
    f(sp20);

Separate scalars that nothing else reads are dead stores, so the compiled code never holds the copy. Here every run of
such statements whose offsets in one symbol tile it from 0, written to the same consecutive stack bytes, becomes
`__builtin_memcpy(sp20, &D_X, 11);`, and the locals become one word array reaching the next stack local (the frame the
draft saw). The symbol is read as m2c read it, so no data is needed. One result per function so far: an SN-N64 2.81
(GCC 2.8.1, `-O2`) asset loader of 212 instructions that picks one of four names; why the original is a string copy
(rather than a record) is not decided by the bytes.

symbol_stack_block_copy
    One child with every run of the function rewritten (the runs share the array, so they go together).

m2c spells a slot it saw only written, inside a wider access, `unkspNN` (`unksp2E` for the last byte of a 15-byte
string copy); those are the same copy's tail. An SN-N64 GCC 2.8.1 text banner of 242 instructions copies four strings,
two of them with such a tail: without it their `lb`/`sb` stayed out of the block move.

A function that copies two constant tables into two buffers of their own (an N64 sound loader, SN GCC 2.8.1: two
tables of four address and size pairs, each eight words read back through a pointer) has two bases; each becomes its
own array.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'symbol_stack_block_copy'
FAMILIES = (FAMILY,)

_IDENT = r'[A-Za-z_]\w*'
_NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'M2C_UNK': 4, 'M2C_UNK8': 1,
          'M2C_UNK16': 2, 'M2C_UNK32': 4, 'char': 1, 'short': 2, 'int': 4}
_TYPE = '|'.join(sorted(_SIZES, key=len, reverse=True))
_COPY = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?:unk)?sp(?P<slot>[0-9A-F]+)(?:\[(?P<index>\d+)\])?\s*=\s*(?:\([^()\n]*\)\s*)?'
                   rf'M2C_FIELD\(&(?P<symbol>{_IDENT}),\s*(?P<type>{_TYPE})\s*\*,\s*(?P<off>{_NUMBER})\);[ \t]*\n')
_DECL = re.compile(rf'(?m)^[ \t]*(?P<type>{_TYPE})[ \t]+(?P<name>(?:unk)?sp)(?P<slot>[0-9A-F]+)(?:\[(?P<count>{_NUMBER})\])?;'
                   r'(?:[ \t]*/\*[^\n]*\*/)?[ \t]*\n')
_ANY_SLOT = re.compile(r'(?m)^[ \t]*(?:struct[ \t]+)?\w+[ \t*]+(?:unk)?sp([0-9A-F]+)\b[^;\n(]*;')


def _runs(copies, declared):
    """Consecutive copy statements of one symbol that tile it from 0 into consecutive stack bytes, two or more each."""
    runs, k = [], 0
    while k < len(copies):
        run, size, base = [], 0, None
        for copy in copies[k:]:
            slot = int(copy['slot'], 16)
            declaration = declared.get(slot)
            if declaration is None:
                break
            width = _SIZES[copy['type']]
            at = slot + int(copy['index'] or 0) * _SIZES[declaration['type']]
            if run and (copy.start() != run[-1].end() or copy['symbol'] != run[0]['symbol']):
                break
            if not run:
                base = at
            if int(copy['off'], 0) != size or at != base + size:
                break
            run.append(copy)
            size += width
        if len(run) > 1 and size > 4:
            runs.append((base, size, run))
            k += len(run)
        else:
            k += 1
    return runs


def _buffer(source, clean, low, high, declared, base, longest, runs):
    """The edits that make the stack buffer at `base` one array filled by block copies, or None."""
    if base not in declared or base % 4 or declared[base]['name'] != 'sp':
        return None
    inside = sorted(slot for slot in declared if base <= slot < base + longest)
    copies = [copy for _, _, run in runs for copy in run]
    # every one of those locals is only copied to by these runs; the first may also be passed on as the buffer
    uses = []
    for slot in inside:
        local = declared[slot]['name'] + declared[slot]['slot']
        for use in re.finditer(rf'(?<![\w.>])(?P<amp>&\s*)?{local}\b', clean[low:high]):
            at = low + use.start()
            if declared[slot].start() <= at < declared[slot].end() or any(c.start() <= at < c.end() for c in copies):
                continue
            after = clean[low + use.end():].lstrip()[:1]
            if slot != base or after in ('[', '=', '.') or after == '+' or after == '-':
                return None
            uses.append((at, low + use.end(), local))
    later = sorted({int(m, 16) for m in _ANY_SLOT.findall(clean[low:high])})
    following = [slot for slot in later if slot >= base + longest]
    room = (following[0] - base) if following else (longest + 3) // 4 * 4
    local = f'sp{base:X}'
    head = declared[base]
    line = source[head.start():head.end()]
    indent = line[:len(line) - len(line.lstrip(' \t'))]
    edits = [(head.start(), head.end(), f'{indent}s32 {local}[{(room + 3) // 4}];\n')]
    edits += [(declared[slot].start(), declared[slot].end(), '') for slot in inside if slot != base]
    for _, size, run in runs:
        first = run[0]
        edits.append((first.start(), run[-1].end(),
                      f'{first["indent"]}__builtin_memcpy({local}, &{first["symbol"]}, {size});\n'))
    return edits + uses


def variants(source, name):
    part = view(source, name)
    if not part or 'M2C_FIELD(&' not in source:
        return []
    clean, low, high = part.clean, part.opening, part.end
    declared = {}
    for hit in _DECL.finditer(clean, low, high):
        declared[int(hit['slot'], 16)] = hit
    runs = _runs(list(_COPY.finditer(clean, low, high)), declared)
    if not runs:
        return []
    # each buffer is rewritten on its own; every one must pass, since a draft with half of them still copies by word
    edits = []
    bases = sorted({base for base, _, _ in runs})
    for number, base in enumerate(bases):
        own = [run for run in runs if run[0] == base]
        longest = max(size for _, size, _ in own)
        if number + 1 < len(bases) and base + longest > bases[number + 1]:
            return []
        found = _buffer(source, clean, low, high, declared, base, longest, own)
        if found is None:
            return []
        edits += found
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
