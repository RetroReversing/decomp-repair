"""Globals far past a base the target holds in a register, written as members of one record at that base.

m2c names every address it sees as a global of its own:

    D_800B8CE8 = 2;            lui $v0, %hi(D_80091BA0); addiu $v0, $v0, %lo(D_80091BA0)
    D_800DFE58 = 2;            lui $a0, 2; addu $a0, $v0, $a0
                               sh $t0, 0x7148($a0)

Separate globals compile to `lui; sh %lo` pairs. The target takes the address of `D_80091BA0`, adds a constant too big
for a 16-bit offset and stores through the sum: the compiler does that for a member of a large record (or record array)
at that symbol, and not for a casted byte offset, which it folds back into one relocation. On a 73-instruction N64
screen-mode setter (SN GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`) the four split globals alone were 2285 points and the record
gave 0.

The assembly is read in order for registers holding `symbol + constant` where the constant came from `lui`/`ori` and an
`addu`; each load or store through one names an address. When the source declares the scalar `D_<address>` for such an
address (the symbol's own name gives the base's address), all of them under one base become members, keeping their
declared types, of a record declared at the base. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'far_record_members'
FAMILIES = (FAMILY,)

SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
         'float': 4}
ACCESS = {'lb': 1, 'lbu': 1, 'sb': 1, 'lh': 2, 'lhu': 2, 'sh': 2, 'lw': 4, 'sw': 4, 'lwc1': 4, 'swc1': 4}
ADDRESS = re.compile(r'[A-Za-z]\w*?_([0-9A-Fa-f]{8})')
CALLER_SAVED = {f'${r}' for r in ['at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3', 't0', 't1', 't2', 't3', 't4', 't5', 't6',
                                  't7', 't8', 't9']}


def _number(text):
    """A constant operand as the splitter writes it: `2`, `0x62B8`, `(0x27148 & 0xFFFF)`, `(0x48000 >> 16)`."""
    hit = re.fullmatch(r'\(\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*(>>\s*16|&\s*0x[Ff]{4})\s*\)', text.strip())
    if hit:
        value = int(hit[1], 0)
        return (value >> 16) & 0xFFFF if hit[2].startswith('>>') else value & 0xFFFF
    if re.fullmatch(r'-?(?:0x[0-9A-Fa-f]+|\d+)', text.strip()):
        return int(text.strip(), 0)
    return None


def accesses(asm):
    """{base symbol: {byte offset from it: access width}} for the loads and stores through a base plus a built
    constant."""
    known = {}  # register -> ('hi', symbol) | (symbol or None, constant)
    found = {}
    delay_of_call = False
    for line in (asm or '').splitlines():
        line = re.sub(r'/\*.*?\*/', ' ', line).strip()
        if not line or line.startswith(('glabel', 'endlabel', '#')):
            continue
        if line.endswith(':'):
            known = {}
            continue
        op, _, rest = line.partition(' ')
        args = [a.strip() for a in rest.split(',')]
        after_call, delay_of_call = delay_of_call, op in ('jal', 'jalr')
        memory = re.fullmatch(r'(.*?)\((\$\w+)\)', args[-1]) if len(args) == 2 else None
        if op in ACCESS and memory:
            base = known.get(memory[2])
            offset = _number(memory[1])
            if base and base[0] not in ('hi', None) and base[1] and offset is not None:
                signed = offset - 0x10000 if 0x8000 <= offset <= 0xFFFF else offset
                found.setdefault(base[0], {})[base[1] + signed] = ACCESS[op]
        value = None
        dest = args[0] if args and args[0].startswith('$') else None
        if op == 'lui' and len(args) == 2:
            symbol = re.fullmatch(rf'%hi\(({IDENT})\)', args[1])
            number = _number(args[1])
            value = ('hi', symbol[1]) if symbol else (None, number << 16) if number is not None else None
        elif op in ('addiu', 'ori') and len(args) == 3:
            source = known.get(args[1])
            low = re.fullmatch(rf'%lo\(({IDENT})\)', args[2])
            number = _number(args[2])
            if low and source == ('hi', low[1]):
                value = (low[1], 0)
            elif source and source[0] != 'hi' and number is not None:
                value = (source[0], source[1] | number if op == 'ori' else source[1] + number)
        elif op == 'addu' and len(args) == 3:
            one, two = known.get(args[1]), known.get(args[2])
            if one and two and 'hi' not in (one[0], two[0]) and None in (one[0], two[0]):
                value = (one[0] or two[0], one[1] + two[1])
        if dest and op not in ('sb', 'sh', 'sw', 'swc1'):
            known.pop(dest, None)
            if value:
                known[dest] = value
        if after_call:  # the call returns past its delay slot with the caller's registers gone
            known = {r: v for r, v in known.items() if r not in CALLER_SAVED}
    return found


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or not asm or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b', part.body):
        return []
    result = source
    changed = False
    for base, offsets in accesses(asm).items():
        address = ADDRESS.fullmatch(base)
        if not address:
            continue
        start = int(address[1], 16)
        members = []
        for offset, width in sorted(offsets.items()):
            if offset <= 0:
                continue
            symbol = f'D_{start + offset:08X}'
            declared = re.search(rf'(?m)^[ \t]*extern\s+(?P<type>{IDENT})\s+{symbol}\s*;[ \t]*\n', result)
            if declared and SIZES.get(declared['type']) == width and not offset % width:
                members.append((offset, width, declared['type'], symbol))
        if not members or members[-1][0] <= 0x7FFF:
            continue
        if any(a[0] + a[1] > b[0] for a, b in zip(members, members[1:])):
            continue
        record = f'Far_{base}'
        if re.search(rf'\b{record}\b', result):
            continue
        # a declaration of the base itself goes with the record's, unless the code names the base
        own = re.search(rf'(?m)^[ \t]*extern\s+[\w \t*]+?\b{base}\s*(?:\[\s*\])?\s*;[ \t]*\n', result)
        rest = result[:own.start()] + result[own.end():] if own else result
        for _, _, _, symbol in members:
            rest = re.sub(rf'(?m)^[ \t]*extern\s+{IDENT}\s+{symbol}\s*;[ \t]*\n', '', rest)
        if re.search(rf'\b{base}\b', rest):
            continue
        fields, at = [], 0
        for offset, width, kind, _ in members:
            if offset > at:
                fields.append(f'  unsigned char pad{at:X}[0x{offset - at:X}];\n')
            fields.append(f'  {kind} f{offset:X};\n')
            at = offset + width
        declaration = f'typedef struct\n{{\n{"".join(fields)}}} {record};\nextern {record} {base};\n'
        for offset, _, _, symbol in members:
            rest = re.sub(rf'(?<![\w.>]){symbol}\b', f'{base}.f{offset:X}', rest)
        current = view(rest, name)
        if not current:
            continue
        head = rest[:current.opening].rfind('\n', 0, rest[:current.opening].rfind(name)) + 1
        result = edit(rest, [(head, head, declaration)])
        changed = True
    return [(FAMILY, result)] if changed else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 40}
