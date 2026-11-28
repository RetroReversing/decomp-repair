"""The stack buffer a call fills, sized to the frame the target reserves for it.

m2c sizes a buffer it passes to a callee by the largest offset the target reads (`char sp10[0x20];`), so the draft's
frame is the buffer's bytes plus the registers it saves plus the outgoing-argument area, and it falls short or long of
the target's `addiu $sp, $sp, -0x40` when the original declared the buffer larger (the callee wrote past what the
function reads back) or when another stack local shares the space. The room for locals in the target is read from its
assembly alone: from the outgoing-argument area (`0x10`) up to the lowest callee-saved store of the prologue
(`sw $s0, 0x38($sp)`). The buffer, the only array a call receives at `spNN`, is resized to fill that room.

One child per sizing: the room less the other `volatile`/scalar stack locals' words (the buffer and the scalars together
fill it), and the whole room (the scalars sit in the buffer's padding). A buffer already that size, no call that takes
it, a frame without saved registers, or two arrays passed to calls: no child. Stores at or above the lowest address-taken stack object are writes into it, not outgoing arguments: a text banner
(SN GCC 2.8.1) whose `strcpy` block moves store bytes into the buffer had its argument area read as 0x38 instead of
0x20, and was offered 232 bytes instead of the 256 that fill the frame.

Hypothesis from reading gcc's frame
layout (locals in declaration order from the argument area up); it was not measured on a matched function, so the
exact judge decides and the family's order is late.
"""
import re

from .integer_repair_support import edit, view
from .stack_gap_padding import _SAVE, argument_area, prologue

FAMILY = 'stack_buffer_frame_fit'
FAMILIES = (FAMILY,)

ARRAY = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>(?:unsigned\s+)?(?:char|u8|s8|s16|u16|s32|u32|f32|int))\s+(?P<name>sp[0-9A-Fa-f]+)\[(?P<n>0x[0-9A-Fa-f]+|\d+)\]\s*;')
SCALAR = re.compile(r'(?m)^[ \t]*(?:volatile\s+)?(?P<type>s32|u32|int|f32|s16|u16|s8|u8|char)\s+sp[0-9A-Fa-f]+\s*;')
_TAKEN = re.compile(r'\baddiu\s+\$(?!sp\b)\w+\s*,\s*\$sp\s*,\s*(0x[0-9a-fA-F]+|\d+)')
SIZES = {'char': 1, 'u8': 1, 's8': 1, 'unsigned char': 1, 's16': 2, 'u16': 2}


def room(asm):
    """(lowest saved offset, argument area) of the target's frame, or None."""
    saves = [int(m[1], 0) for m in _SAVE.finditer(prologue(asm))]
    if not saves:
        return None
    low = min(saves)
    # a stack object whose address is taken starts above the outgoing arguments: stores into it are not arguments
    objects = [at for at in (int(m, 0) for m in _TAKEN.findall(asm)) if 16 <= at < low]
    return low, argument_area(asm, min(objects, default=low))


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    found = room(asm)
    if not found:
        return []
    low, area = found
    body = part.clean[part.opening:part.end]
    arrays = list(ARRAY.finditer(part.clean, part.opening, part.end))
    passed = [a for a in arrays if re.search(rf'[(,]\s*{a["name"]}\s*[,)]', body)]
    if len(passed) != 1 or len(arrays) != 1:
        return []
    buf = passed[0]
    scalars = sum(4 if SIZES.get(m['type'], 4) <= 4 else 8 for m in SCALAR.finditer(part.clean, part.opening, part.end))
    unit = SIZES.get(buf['type'], 4)
    out = []
    for taken in (scalars, 0):
        bytes_ = (low - area - taken) // 8 * 8
        count = bytes_ // unit
        if bytes_ <= 0 or count == int(buf['n'], 0):
            continue
        spelling = f'0x{count:X}' if buf['n'].lower().startswith('0x') else str(count)
        text = edit(source, [(buf.start('n'), buf.end('n'), spelling)])
        if (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 1500}  # the registry: no caller wiring (registry.py)
