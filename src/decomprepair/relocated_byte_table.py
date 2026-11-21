"""Recover separate byte-table and output-buffer objects in a KMC remainder loop."""

import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names
from .mips_addresses import addresses

LABEL = r'\.L\w+'
ZERO = r'(?:0x0|0)?'
OFFSET = rf'(?: \+ (?P<{{key}}off>{NUMBER}))?'
WITNESS = re.compile(
    rf'(?m)^lui \$a2, %hi\((?P<buffer>{IDENT}){OFFSET.format(key="buffer")}\)\n'
    r'addiu \$a2, \$a2, %lo\((?P=buffer)'
    r'(?(bufferoff) \+ (?:(?P=bufferoff)|\((?P=bufferoff) & 0xFFFF\)))\)\n'
    rf'(?P<loop>{LABEL}):\ndivu \$zero, \$a0, \$a1\n'
    rf'bnez \$a1, (?P<divide>{LABEL})\nnop\nbreak (?:7|0x7)\n(?P=divide):\n'
    r'mflo \$a0\nmfhi \$v1\n'
    rf'lui \$v0, %hi\((?P<table>{IDENT}){OFFSET.format(key="table")}\)\n'
    r'lw \$v0, %lo\((?P=table)(?(tableoff) \+ (?P=tableoff))\)\(\$v0\)\n'
    rf'addu \$v0, \$v0, \$v1\nlbu \$v0, {ZERO}\(\$v0\)\n'
    r'addiu \$a2, \$a2, -(?:1|0x1)\nbnez \$a0, (?P=loop)\n'
    rf'sb \$v0, {ZERO}\(\$a2\)\njr \$ra\n(?:addu \$v0, \$a2, \$zero|move \$v0, \$a2)$'
)

BUFFER = re.compile(
    rf'(?m)^[ \t]*var_a2 = (?:&(?P<raw>{IDENT}) \+ (?P<rawoff>{NUMBER})'
    rf'|\(void \*\)\(&(?P<cast>{IDENT})\); var_a2 = \(void \*\)'
    rf'\(\(char \*\)var_a2 \+ \(s32\)\((?P<castoff>{NUMBER})\)\));'
)
LOOKUP = re.compile(
    rf'(?<== )\*(?:\(s32 \*\))?\(M2C_FIELD\(&(?P<table>{IDENT}), s32 \*, (?P<offset>{NUMBER})\) \+ temp_hi\)(?=;)'
)


def _target(asm):
    if 'divu' not in asm or 'lbu' not in asm or '%hi(' not in asm:
        return None
    lines = (' '.join(re.sub(r'/\*[^\n]*?\*/|#.*', '', line).split())
             for line in abi_register_names(asm).splitlines())
    return WITNESS.search('\n'.join(filter(None, lines)))


def applies(asm):
    return _target(asm) is not None


def _address(resolve, name, offset):
    base = resolve(name)
    return None if base is None else base + integer(offset or '0')


def rewrite(source, name, asm, header='', resolve=None):
    """Use the two relocated objects and a byte-indexed lookup where the target proves them."""
    if resolve is None or 'M2C_FIELD' not in source or not (target := _target(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    start = part.opening + 1
    buffer = list(BUFFER.finditer(part.clean, start, part.end))
    lookup = list(LOOKUP.finditer(part.clean, start, part.end))
    if len(buffer) != 1 or len(lookup) != 1:
        return None
    buffer, lookup = buffer[0], lookup[0]
    if not buffer.end() < lookup.start() or not re.search(
        r'\btemp_hi = var_a0 % arg1;\s+var_a0 = var_a0 / arg1;', part.clean[buffer.end():lookup.start()]
    ):
        return None
    if not re.search(r'\b(?:u8|char) \*var_a2;', part.clean[start:buffer.start()]):
        return None

    buffer_addr = _address(resolve, buffer['raw'] or buffer['cast'], buffer['rawoff'] or buffer['castoff'])
    table_addr = _address(resolve, lookup['table'], lookup['offset'])
    raw_addresses = addresses(asm)
    if buffer_addr == table_addr or any(address not in raw_addresses for address in (buffer_addr, table_addr)):
        return None
    if (buffer_addr != _address(resolve, target['buffer'], target['bufferoff'])
            or table_addr != _address(resolve, target['table'], target['tableoff'])):
        return None

    buffer_alias = f'D_{buffer_addr:08X}'
    table_alias = f'D_{table_addr:08X}'
    for alias, address in ((buffer_alias, buffer_addr), (table_alias, table_addr)):
        if resolve(alias) != address or re.search(rf'\b{alias}\b', source + '\n' + header):
            return None
    declaration = find(source, name)[0]
    indentation = part.clean[buffer.start():buffer.end()].split('var_a2', 1)[0]
    return edit(source, [
        (declaration, declaration, f'extern u8 {buffer_alias}[];\nextern u8 *{table_alias};\n\n'),
        (*buffer.span(), f'{indentation}var_a2 = {buffer_alias};'),
        (*lookup.span(), f'{table_alias}[temp_hi]'),
    ])
