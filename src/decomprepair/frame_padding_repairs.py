"""Stack the target reserves that no local of the draft explains: a volatile scratch the original declared.

An N64 function's frame has the outgoing-argument area at the bottom, then its locals, then the registers it saves. When
the lowest saved register sits higher than the argument area, the difference is local storage, and a draft with no
stack locals reserves less (a 0x38 frame where the draft's was 0x30). The original often had a variable the compiler
kept in memory (a `volatile` scratch). The rewrite declares one of that size; the compiler and the judge decide. Only for
functions with no stack objects of their own: a draft that names `spXX` locals or a local array is left to the families
that size those.
"""
import re

from . import mips_stack, passthrough_argument_repairs
from .integer_repair_support import edit, view

FAMILY = 'unused_frame_padding'
FAMILIES = (FAMILY,)
_SAVE = re.compile(r'\b(?:sw|sd|swc1|sdc1)\s+\$(?:s[0-8]|ra|fp|f2[0-9]|f3[01]|fs\d)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_ARGUMENT = re.compile(r'\b(?:sw|sd|swc1|sdc1|sh|sb)\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_FRAME = re.compile(r'\baddiu\s+\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)')


def padding(asm):
    """Bytes of local storage the target's frame has between its argument area and its saved registers, or 0."""
    frame = _FRAME.search(asm or '')
    saves = [int(m[1], 0) for m in _SAVE.finditer(asm or '')]
    if not frame or not saves:
        return 0
    lowest = min(saves)
    arguments = 16 if re.search(r'\bjalr?\b', asm) else 0
    for match in _ARGUMENT.finditer(asm):
        offset = int(match[1], 0)
        if offset < lowest and offset + 4 > arguments:
            arguments = (offset + 4 + 7) // 8 * 8
    return lowest - arguments if lowest - arguments >= 4 else 0


def _declarations(size):
    if size % 8 == 0:
        return ['volatile u64 scratch;'] if size == 8 else ['volatile u64 scratch[%d];' % (size // 8)]
    return (['volatile u64 scratch;'] * (size // 8) + ['volatile s32 scratch_word;']) if size > 8 else ['volatile s32 scratch;']


def variants(source, name, asm):
    part = view(source, name)
    size = padding(asm)
    if not part or not size or size > 64:
        return []
    if re.search(r'\bsp[0-9A-Fa-f]+\b|\bvolatile\b|\bscratch\b', part.clean[part.opening:part.end]):
        return []
    lines = ''.join('\n    ' + declaration for declaration in _declarations(size))
    return [(FAMILY, edit(source, [(part.opening + 1, part.opening + 1, lines)]))]


def forwarded_variants(source, name, header, rows, asm, frame_delta):
    """Compose one measured reservation and one missing incoming call argument."""
    if frame_delta <= 0 or sum(marker not in (' ', 's') for marker, _, _ in rows) != 1:
        return []
    frame_rows = [row if row[0] == 's' else (' ', row[1], row[1]) for row in rows]
    frame = mips_stack.repair_layout(frame_rows) or {}
    if (frame.get('inferred_growth') != frame_delta or frame.get('local_deltas')
            or padding(asm) != frame_delta):
        return []
    call_rows = [row if row[0] != 's' else (' ', row[1], row[1]) for row in rows]
    forwarded = passthrough_argument_repairs.shifted_call_variants(source, name, header, asm, call_rows)
    return [('frame_reservation_with_forwarded_argument', padded)
            for _, candidate in forwarded for _, padded in variants(candidate, name, asm)]
