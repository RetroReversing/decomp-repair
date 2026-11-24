"""Frame the target reserves below its lowest stack object: a local array the original declared and never read.

m2c names a stack local by the offset the target gives it (`s32 sp60;` for the word at `0x60($sp)`) but a draft that
declares it puts it at the bottom of the locals, right above the outgoing-argument area: `0x10($sp)`, in a frame
0x50 bytes smaller, and every saved register and the epilogue's `addiu $sp` differ (a KMC GCC 2.7.2 function: score
16, all of it stack rows). The original had an unused array too (`s32 pad[20];`, 0x50 bytes) declared after its other
locals, and with it the object is at 0x60 and the frame is the target's: 16 -> 0. The size is read from the target
alone: the lowest declared `spNN`, minus the outgoing-argument area (16 bytes when the function calls, more when it
stores arguments below that object). The same 0x50 and 0x80 byte paddings (`sp10[32]`, `pad[32]`) recurred in
three other matched functions of the project, and the families that size a frame gap from the judge's rows
(`inferred_frame_reservation`, `measured_grow_unused_frame_array`) stop at 32 bytes and want every changed row to
agree, which an address-taken local's own offset breaks.

Proposals only (the judge decides): the array after the last local, where it sits below the others (the usual
place), and as the first declaration (above them). Hypothesis, not read from the compiler: GCC 2.7.2 allocates
locals in declaration order, downward from the saved registers.
"""
import re

from .frame_padding_repairs import declaration_ends
from .integer_repair_support import edit, view

FAMILY = 'stack_gap_padding'
FAMILIES = (FAMILY,)
MINIMUM = 16  # smaller gaps are the 8-32 byte families', which have the judge's rows as evidence
MAXIMUM = 0x400

_NUMBER = r'(0x[0-9a-fA-F]+|\d+)'
_FRAME = re.compile(r'\baddiu\s+\$sp\s*,\s*\$sp\s*,\s*-' + _NUMBER)
_SAVE = re.compile(r'\b(?:sw|sd|swc1|sdc1)\s+\$(?:s[0-8]|ra|fp|f2[0-9]|f3[01])\s*,\s*' + _NUMBER + r'\(\$sp\)')
_STORE = re.compile(r'\b(?:sw|sd|sh|sb|swc1|sdc1)\s+\$\w+\s*,\s*' + _NUMBER + r'\(\$sp\)')
_ACCESS = re.compile(r'(?:\b(?:lw|ld|lh|lhu|lb|lbu|lwc1|ldc1|sw|sd|sh|sb|swc1|sdc1)\s+\$\w+\s*,\s*' + _NUMBER
                     + r'\(\$sp\)|\baddiu\s+\$(?!sp\b)\w+\s*,\s*\$sp\s*,\s*' + _NUMBER + ')')
_LOCAL = re.compile(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t]+)+?\**[ \t]*sp(?P<offset>[0-9A-Fa-f]+)(?:\[[^\]\n]*\])?[ \t]*;')


def argument_area(asm, floor):
    """Bytes at the bottom of the frame the target's calls use: 16 for a function that calls, more when it stores a
    word below `floor` (the lowest object, in bytes) that no object explains. 0 for a leaf."""
    area = 16 if re.search(r'\bjalr?\b', asm) else 0
    for hit in _STORE.finditer(asm):
        offset = int(hit[1], 0)
        if area <= offset < floor:
            area = (offset + 4 + 7) // 8 * 8
    return area


def prologue(asm):
    """The text up to and including the delay slot of the first call or branch: where the target saves its registers
    (a later store of a saved register's value into a local is not a save)."""
    lines = asm.splitlines()
    for index, line in enumerate(lines):
        if re.search(r'\b(?:jalr?|jr|j|b|beq|bne|beqz|bnez|bgez|bgtz|blez|bltz|bc1[tf])\b', line):
            return '\n'.join(lines[:index + 2])
    return asm


def gap(source_body, asm):
    """(bytes, lowest object offset) the target reserves under its lowest stack object, or None.

    The object is the lowest declared `spNN` that the target touches, or, in a function with no stack object at all
    (every access to the frame is a register save or an argument), the lowest saved register's slot: the whole area
    between is then an array the original never used."""
    frame = _FRAME.search(asm or '')
    saved = [int(m[1], 0) for m in _SAVE.finditer(prologue(asm or ''))]
    if not frame or not saved:
        return None
    declared = {int(m['offset'], 16) for m in _LOCAL.finditer(source_body)}
    touched = {int(m[1] or m[2], 0) for m in _ACCESS.finditer(asm)} - set(saved)
    if declared:
        low = min(declared)
        # the name is the target's offset only when the target touches it, below its saved registers
        if low not in touched or low >= min(saved):
            return None
    elif any(offset >= 16 for offset in touched):
        return None  # a stack object no declaration names: the layout families' business
    else:
        low = min(saved)
    if low >= int(frame[1], 0):
        return None
    size = low - argument_area(asm, low)
    return (size, low) if MINIMUM <= size <= MAXIMUM and size % 4 == 0 else None


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    found = gap(part.clean[part.opening:part.end], asm)
    if not found or re.search(r'\b(?:volatile|pad|__repair_gap_pad)\w*\b', part.clean[part.opening:part.end]):
        return []
    size = found[0]
    line = f'\n    s32 pad[{size // 4}];' if size % 8 == 0 else f'\n    u8 pad[{size}];'
    ends = declaration_ends(part)
    places = list(dict.fromkeys(([ends[-1]] if ends else []) + [part.opening + 1]))
    return [(FAMILY, edit(source, [(at, at, line)])) for at in places]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
