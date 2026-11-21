"""Restore a stack-backed input buffer and its alignment in a KMC draft."""

import re
from dataclasses import dataclass

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines

SAVED = r'\$s[0-7]'
MOVE = r'(?:addu {dest}, {src}, \$zero|move {dest}, {src})'
ENTRY = re.compile(
    rf'(?m)^addiu \$sp, \$sp, -(?P<frame>{NUMBER})\n'
    rf'sw (?P<input>{SAVED}), (?P<input_slot>{NUMBER})\(\$sp\)\n'
    r'(?:addu (?P=input), \$a0, \$zero|move (?P=input), \$a0)\n'
    rf'sw (?P<cursor>{SAVED}), (?P<cursor_slot>{NUMBER})\(\$sp\)\n'
    rf'addiu (?P=cursor), \$sp, (?P<address>{NUMBER})\n'
    rf'srl (?P=cursor), (?P=cursor), (?P<shift>{NUMBER})\n'
    r'sll (?P=cursor), (?P=cursor), (?P=shift)\n'
    r'(?:addu \$a1, (?P=cursor), \$zero|move \$a1, (?P=cursor))\n'
    rf'sw \$ra, (?P<return_slot>{NUMBER})\(\$sp\)\n'
    rf'jal (?P<callee>{IDENT})\naddiu \$a2, \$zero, (?P<length>{NUMBER})$'
)
SETUP = re.compile(
    rf'(?m)^[ \t]*(?P<address>{IDENT}) = \(\(u32\) &(?P<slot>{IDENT}) >> (?P<shift>{NUMBER})\) '
    rf'\* (?P<align>{NUMBER});\s*'
    rf'(?P<callee>{IDENT})\((?:(?P<arg>{IDENT}), )?(?P=address), (?P<length>{NUMBER})\);'
)


@dataclass(frozen=True)
class Read:
    callee: str
    shift: int
    extent: int
    length: int
    halfword: int


def _evidence(asm):
    if 'srl' not in asm or 'sll' not in asm or 'lhu' not in asm:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm))
    if not (head := ENTRY.search(text)) or head['cursor'] == head['input']:
        return None
    shift = integer(head['shift'])
    if shift not in (3, 4, 5):
        return None
    alignment = 1 << shift
    base = integer(head['address']) - (alignment - 1)
    slots = sorted(integer(head[field]) for field in ('input_slot', 'cursor_slot', 'return_slot'))
    extent = slots[0] - base
    length = integer(head['length'])
    frame = integer(head['frame'])
    if (base < 16 or not 0 < length <= extent - (alignment - 1)
            or not alignment <= extent <= 64 or slots[1:] != [slots[0] + 4, slots[0] + 8]
            or slots[-1] + 4 > frame):
        return None
    cursor = re.escape(head['cursor'])
    saved = re.escape(head['input'])
    rest = text[head.end():]
    result = re.match(rf'\n(?:addu \$a0, \$zero, \$zero|move \$a0, \$zero)\n'
                      rf'lhu {cursor}, (?P<field>{NUMBER})\({cursor}\)', rest)
    if not result or not 0 <= (offset := integer(result['field'])) <= length - 2 or offset % 2:
        return None
    # A later call to the same routine uses the saved incoming argument and the
    # allocation result. The original incoming register is still live at the first call.
    reuse = re.search(
        rf'(?m)^{MOVE.format(dest=r"\$a0", src=saved)}\n'
        rf'{MOVE.format(dest=r"\$a1", src=r"\$v0")}\n'
        rf'(?:[^\n]+\n){{0,2}}jal {head["callee"]}\n{MOVE.format(dest=r"\$a2", src=cursor)}$',
        rest[result.end():],
    )
    if not reuse:
        return None
    return Read(head['callee'], shift, extent, length, offset)


def applies(asm):
    return _evidence(asm) is not None


def rewrite(source, name, asm):
    """Keep the evidenced stack extent and restore the first call's incoming argument."""
    if 'M2C_FIELD' not in source or not (target := _evidence(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(s32 (?P<arg>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    # The two drafts differ only in whether m2c dropped the leading call argument.
    alignments = list(SETUP.finditer(part.clean, part.opening + 1, part.end))
    if len(alignments) != 1:
        return None
    setup = alignments[0]
    argument, address, slot = signature['arg'], setup['address'], setup['slot']
    alignment = 1 << target.shift
    if (setup['callee'] != target.callee or integer(setup['shift']) != target.shift
            or integer(setup['align']) != alignment or integer(setup['length']) != target.length
            or setup['arg'] not in (None, argument)):
        return None
    body = part.clean[part.opening + 1:part.end]
    if len(re.findall(rf'\b{slot}\b', body)) != 2:
        return None
    start = part.opening + 1
    locals_before_read = part.clean[start:setup.start()]
    if not re.fullmatch(rf'(?:\s*(?:M2C_UNK|s32|u32) {IDENT};)+\s*', locals_before_read):
        return None
    declaration = re.search(rf'\b(?:M2C_UNK|s32) {slot};', locals_before_read)
    if not declaration:
        return None
    tail = part.clean[setup.end():part.end]
    field = re.match(rf'\s*{IDENT} = [^;]*M2C_FIELD\({address}, u16 \*, ({NUMBER})\)', tail)
    if not field or integer(field[1]) != target.halfword:
        return None
    other_call = re.search(rf'\b{target.callee}\({argument}, {IDENT}, {IDENT}\);', tail)
    if not other_call:
        return None
    cast = re.search(rf'\(u32\) &{slot}\b', part.clean[setup.start():setup.end()])
    extra = [(setup.end('callee') + 1, setup.end('callee') + 1, argument + ', ')] if not setup['arg'] else []
    return edit(source, [
        (start + declaration.start(), start + declaration.end(), f'u8 {slot}[{target.extent}];'),
        (setup.start() + cast.start(), setup.start() + cast.end(), f'((u32) &{slot} + 0x{alignment - 1:X})'),
        *extra,
    ])
