"""Reconstruct short KMC loops whose back edge names the function entry."""

import re

from .integer_repair_support import IDENT
from .mips import abi_register_names, normalized_integer_lines
from .mips_returns import instructions

_WORD = re.compile(r'/\*\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})\s*\*/')
_SCAN = re.compile(
    r'lb \$v0, (?:0)?\(\$a0\)\nsltu \$v1, \$a0, \$a1\n'
    r'xori \$v0, \$v0, (?P<byte>\d+)\nsltu \$v0, \$zero, \$v0\nand \$v0, \$v0, \$v1\n'
    rf'bnel \$v0, \$zero, (?P<target>{IDENT}|\.L\w+)\n'
    r'addiu \$a0, \$a0, 1\njr \$ra\naddu \$v0, \$a0, \$zero'
)
_POLL = re.compile(
    rf'lui \$v0, %hi\((?P<symbol>{IDENT})\)\nlw \$v0, %lo\((?P=symbol)\)\(\$v0\)\n'
    rf'bnez \$v0, (?P<target>{IDENT}|\.L\w+)\nnop\njr \$ra\nnop'
)


def _match(asm):
    if 'bnel' not in asm and 'bnez' not in asm:
        return None
    text = '\n'.join(normalized_integer_lines(instructions(abi_register_names(asm))))
    encoded = [(int(m[1], 16), int(m[2], 16)) for m in _WORD.finditer(asm)]
    if not encoded:
        return None
    start = encoded[0][0]
    if any(address != start + index * 4 for index, (address, _) in enumerate(encoded)):
        return None
    for pattern, branch, opcode in ((_SCAN, 5, 0x54400000), (_POLL, 2, 0x14400000)):
        match = pattern.fullmatch(text)
        if not match or len(encoded) != text.count('\n') + 1:
            continue
        address, word = encoded[branch]
        delta = (word & 0xFFFF) - (0x10000 if word & 0x8000 else 0)
        if word & 0xFFFF0000 != opcode or address + 4 + 4 * delta != start:
            continue
        if match['target'].startswith('.L') and match['target'].upper() != f'.L{start:08X}':
            continue
        if pattern is _SCAN and (int(match['byte']) > 127 or encoded[2][1] != 0x38420000 | int(match['byte'])):
            continue
        return match, pattern
    return None


def applies(asm):
    return _match(asm) is not None


def candidate(asm, name, header=''):
    """Use the complete branch and delay slot when m2c cannot resolve the back edge."""
    match = _match(asm)
    if not match or not re.fullmatch(IDENT, name) or re.search(rf'\b{re.escape(name)}\s*\(', header):
        return None
    mode, pattern = match
    if mode['target'] != name and not mode['target'].startswith('.L'):
        return None
    if pattern is _SCAN:
        return f'''s8 *{name}(s8 *cursor, u32 end) {{
    while ((*cursor != {mode['byte']}) & ((u32)cursor < end)) {{
        cursor++;
    }}
    return cursor;
}}'''
    symbol = mode['symbol']
    if symbol == name or re.search(rf'\b{symbol}\b', header):
        return None
    return f'''extern volatile s32 {symbol};

void {name}(void) {{
    do {{
    }} while ({symbol} != 0);
}}'''
