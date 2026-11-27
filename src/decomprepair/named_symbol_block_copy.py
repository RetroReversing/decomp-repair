"""m2c's copy of constant data from one label per element into stack scalars, written back as block copies.

`u8 colour[3] = { 255, 0, 0 };` or `char text[256]; strcpy(text, "...");` compiles to a GCC block move: the data's
address in one register, three registers loaded off it, then stored. A split project labels each byte or word the move
reads, so m2c names one global per load and one local per store:

    s32 sp20;
    s8 sp21;
    s8 sp22;
    ...
    base = &D_80001000;
    sp20 = *base;
    sp21 = D_80001001;
    sp22 = D_80001002;
    f(&sp20);

Only `sp20` escapes, so the other stores are dead. The labels carry their addresses, so a run of such statements whose
source addresses and stack slots advance together is one copy: `__builtin_memcpy(&sp20, &D_80001000, 3);`, with
`sp20` declared as the array that reaches the next stack object. For the last buffer that is the first register save
the target makes (`sw $s0, 0x1A8($sp)`), which is what gives the frame its size.

`symbol_stack_block_copy` reads the same move where m2c spelled it as `M2C_FIELD(&D_X, ...)` offsets, and
`byte_run_struct_copy` where every local is a byte. An SN-N64 GCC 2.8.1 (`-O2`) HUD routine of 84 instructions went
from 3819 to 1343 with the copies alone.

named_symbol_block_copy
    One child with every run rewritten (the runs share the buffers, so they go together).
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'named_symbol_block_copy'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_SIZES = {'signed char': 1, 'unsigned char': 1, 'unsigned short': 2, 'unsigned int': 4, 's8': 1, 'u8': 1, 'char': 1,
          's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4, 'float': 4, 'M2C_UNK': 4,
          'M2C_UNK8': 1, 'M2C_UNK16': 2, 'M2C_UNK32': 4}
_TYPE = '|'.join(sorted(_SIZES, key=len, reverse=True))
_EXTERN = re.compile(rf'(?m)^[ \t]*extern[ \t]+(?P<type>{_TYPE})[ \t]+(?P<name>D_(?:\w+_)?(?P<address>[0-9A-F]{{8}}))[ \t]*;')
_DECL = re.compile(rf'(?m)^[ \t]*(?P<type>{_TYPE})[ \t]+sp(?P<slot>[0-9A-F]+);(?:[ \t]*/\*[^\n]*\*/)?[ \t]*\n')
_ANY_SLOT = re.compile(r'(?m)^[ \t]*(?:struct[ \t]+)?[A-Za-z_]\w*[ \t*]+sp([0-9A-F]+)\b[^;\n(]*;')
_COPY = re.compile(rf'(?m)^(?P<indent>[ \t]*)sp(?P<slot>[0-9A-F]+)[ \t]*=[ \t]*(?:\([ \t]*(?:{_TYPE})[ \t]*\)[ \t]*)?'
                   rf'(?P<value>\(\*{_ID}\)|\*{_ID}|{_ID})[ \t]*;[ \t]*\n')
_POINT = re.compile(rf'(?m)^[ \t]*(?P<pointer>{_ID})[ \t]*=[ \t]*&(?P<symbol>D_\w+)[ \t]*;[ \t]*\n')
_SAVE = re.compile(r'\bsw\s+\$(?:s[0-7]|fp|ra)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\(\$sp\)')


def _runs(clean, opening, end, symbols, slots):
    """Runs of adjacent copy statements whose source addresses and stack slots advance together."""
    pointers = {}
    for hit in _POINT.finditer(clean, opening, end):
        pointers.setdefault(hit['pointer'], set()).add(hit['symbol'])
    reads = []
    for hit in _COPY.finditer(clean, opening, end):
        value = hit['value'].strip('()')
        if value.startswith('*'):
            aimed = pointers.get(value[1:], set())
            value = next(iter(aimed)) if len(aimed) == 1 else None
        slot = int(hit['slot'], 16)
        if value in symbols and slot in slots:
            reads.append((hit, slot, value))
    runs, k = [], 0
    while k < len(reads):
        hit, slot, symbol = reads[k]
        address, width = symbols[symbol]
        run, size = [reads[k]], width
        for following in reads[k + 1:]:
            if (following[0].start() != run[-1][0].end() or following[1] != slot + size
                    or symbols[following[2]][0] != address + size):
                break
            run.append(following)
            size += symbols[following[2]][1]
        if len(run) > 1 and size > 2 and slot % 4 == 0:
            runs.append((slot, size, symbol, run))
        k += len(run)
    return runs, pointers


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or 'D_' not in source:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    symbols = {hit['name']: (int(hit['address'], 16), _SIZES[hit['type']]) for hit in _EXTERN.finditer(part.clean)}
    slots = {int(hit['slot'], 16): hit for hit in _DECL.finditer(clean, opening, end)}
    runs, pointers = _runs(clean, opening, end, symbols, slots)
    if not runs:
        return []
    longest = {}
    for slot, size, _, _ in runs:
        longest[slot] = max(size, longest.get(slot, 0))
    absorbed = {slot for base, size in longest.items() for slot in slots if base <= slot < base + size}
    copies = [hit for *_, run in runs for hit, _, _ in run]
    # an absorbed local is only written by these copies; a buffer's first may also have its address passed on
    for slot in absorbed:
        declaration = slots[slot]
        for use in re.finditer(rf'(?<![\w.>])(?P<amp>&\s*)?sp{slot:X}\b', clean[opening:end]):
            at = opening + use.start()
            if declaration.start() <= at < declaration.end() or any(c.start() <= at < c.end() for c in copies):
                continue
            if slot not in longest or not use['amp']:
                return []
    others = {int(found, 16) for found in _ANY_SLOT.findall(clean[opening:end])} - absorbed
    saves = [int(found, 0) for found in _SAVE.findall(asm or '')]
    edits = []
    for base, size in sorted(longest.items()):
        following = [slot for slot in others | set(longest) if slot >= base + size]
        if not following:
            following = [offset for offset in saves if offset >= base + size]
        room = min(following) - base if following else size
        head = slots[base]
        line = source[head.start():head.end()]
        indent = line[:len(line) - len(line.lstrip(' \t'))]
        edits.append((head.start(), head.end(), f'{indent}s32 sp{base:X}[{(room + 3) // 4}];\n'))
    edits += [(slots[slot].start(), slots[slot].end(), '') for slot in absorbed if slot not in longest]
    for base, size, symbol, run in runs:
        first = run[0][0]
        edits.append((first.start(), run[-1][0].end(),
                      f'{first["indent"]}__builtin_memcpy(&sp{base:X}, &{symbol}, {size});\n'))
    # a pointer that only the copies read goes, with its declaration
    for pointer in pointers:
        rest = clean[opening:end]
        spans = [hit for hit in copies if re.search(rf'\b{pointer}\b', hit[0])]
        if not spans:
            continue
        sets = [hit for hit in _POINT.finditer(clean, opening, end) if hit['pointer'] == pointer]
        declared = re.search(rf'(?m)^[ \t]*(?:{_TYPE}|void)[ \t]*\*[ \t]*{pointer}[ \t]*;[ \t]*\n', rest)
        uses = len(re.findall(rf'\b{pointer}\b', rest))
        if declared and uses == len(spans) + len(sets) + 1:
            edits += [(hit.start(), hit.end(), '') for hit in sets]
            edits.append((opening + declared.start(), opening + declared.end(), ''))
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 100,
          'archs': ('mips',)}
