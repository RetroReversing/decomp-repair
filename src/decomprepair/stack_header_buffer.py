"""Restore a serialized stack buffer whose individual fields m2c declares as separate locals."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .measured_stack_drafts import _lines
from .stack_read_retry import _decimal

START = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>\d+)\naddiu \$a0, \$sp, (?P<base>\d+)\n'
    rf'sw \$ra, (?P<save>\d+)\(\$sp\)\njal (?P<read>{IDENT})\naddiu \$a1, \$zero, (?P<size>\d+)\n'
)
FIELD = re.compile(
    rf'jal (?P<call>{IDENT})\naddiu \$a0, \$sp, (?P<address>\d+)\n'
    rf'lui \$at, %hi\((?P<symbol>{IDENT}) \+ (?P<offset>\d+)\)\n'
    r'(?P<store>sh|sw) \$v0, %lo\((?P=symbol) \+ (?P=offset)\)\(\$at\)\n'
)


def _evidence(asm):
    if 'jal' not in asm or '%hi' not in asm:
        return None
    lines = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                      if not line.startswith(('glabel ', 'endlabel ')))
    lines = _decimal(lines).replace('addu $v0, $zero, $zero', 'move $v0, $zero')
    start = START.match(lines)
    if not start:
        return None
    frame, base, size, save = (int(start[key]) for key in ('frame', 'base', 'size', 'save'))
    if base < 16 or base % 4 or size > 128 or base + size > save or save + 4 > frame or frame % 8:
        return None
    fields = []
    previous_end = 1  # The source names the read destination separately from the fields.
    pos = start.end()
    while field := FIELD.match(lines, pos):
        width = 2 if field['store'] == 'sh' else 4
        offset = int(field['address']) - base
        if offset < previous_end or offset + width > size:
            return None
        fields.append((field['call'], field['symbol'], int(field['offset']), f's{width * 8}', offset))
        previous_end = offset + width
        pos = field.end()
    if not 2 <= len(fields) <= 8:
        return None
    if lines[pos:] != f'lw $ra, {save}($sp)\nmove $v0, $zero\njr $ra\naddiu $sp, $sp, {frame}':
        return None
    return start['read'], base, size, fields


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm, header=''):
    """Combine the read destination and each observed field address into one byte array."""
    local = '__repair_header_bytes'
    if 'M2C_FIELD' not in source or local in source + header:
        return None
    if not (target := _evidence(asm)) or not (part := view(source, name)):
        return None
    read, base, size, fields = target
    declarations = [f'M2C_UNK sp{base:X};']
    calls = [f'{read}(&sp{base:X}, {size});']
    replacement = [f'{read}({local}, {size});']
    for call, symbol, dest, kind, offset in fields:
        slot = f'sp{base + offset:X}'
        field = f'M2C_FIELD(&{symbol}, {kind} *, {dest})'
        declarations.append(f'M2C_UNK {slot};')
        calls.append(f'{field} = {call}(&{slot});')
        replacement.append(f'{field} = {call}({local} + {offset});')
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = ' '.join(_decimal(part.clean[start:end]).split())
    if not _shape(' '.join(declarations + calls + ['return 0;'])).fullmatch(body):
        return None
    # m2c guessed word pointers for these prototypes. The field addresses can be unaligned.
    # Only replace the placeholder types on m2c's own declarations.
    edits = []
    outside = part.clean[:start] + part.clean[end:]
    for callee in sorted({read, *(call for call, *_ in fields)}):
        if re.search(rf'\b{callee}\b', header):
            return None
        first_arg = re.compile(
            rf'(?m)^[ \t]*(?:extern[ \t]+)?(?:M2C_UNK|s16|s32)[ \t]+{callee}'
            r'\s*\(\s*(?P<ptr>M2C_UNK\s*\*)\s*(?:,\s*M2C_UNK\s*)?\);[ \t]*/\* extern \*/[ \t]*$'
        )
        prototypes = list(first_arg.finditer(source, 0, part.opening))
        if len(prototypes) != 1 or len(re.findall(rf'\b{callee}\b', outside)) != 1:
            return None
        pointer = prototypes[0].span('ptr')
        if not part.clean[pointer[0]:pointer[1]].strip():
            return None
        edits.append((*pointer, 'void *'))
    replacement.append('return 0;')
    edits.append((start, end, f'\n    u8 {local}[{size}];\n\n    ' + '\n    '.join(replacement) + '\n'))
    return edit(source, edits)
