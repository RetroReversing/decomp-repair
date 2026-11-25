"""An unused array that sizes the frame, when the stack frame is the only thing the draft gets wrong.

Three matched KMC GCC 2.7.2 N64 functions (`-G0 -mips3 -mgp32 -mfp32 -O2`) each had a local the original never read:
`char buf[0x20];`, `f32 spare[4];` and `char big[0xF8];`, declared among real locals (arrays and structs of their own, so
`frame_padding_repairs` (a function with no stack objects) and `stack_gap_padding` (m2c's `spNN` locals) do not apply).
Without it the draft's frame was the target's minus the array: every difference was a stack row (`addiu $sp, $sp, -0x58`
against -0x38, and every saved register and local at another offset: 22, 55 and 14 points, nothing else wrong), and
with it each was 0. No family offered an array of the missing size: `unused_frame_padding` adds one word.

When the judge's rows show only stack-offset differences and the target's frame is bigger than the candidate's by
`gap` bytes (a multiple of 8), this offers `char frame_pad[gap];` declared in each position of the function's leading
declarations (first, after each declaration, last: the gap lands below or above the locals it follows, and the
offsets of the others shift with it), and the same as `s32 frame_pad[gap / 4]` at the first and last. The judge decides
which position gives the target's offsets. The caller passes the judge's rows
(decompdecomp: `diff_gated_repairs`), so the module declares no `REPAIR`. It is scaffolding (the original really had an unused local, but not under
this name); the match report says so.
"""
import re

from .frame_padding_repairs import declaration_ends
from .integer_repair_support import edit, view

FAMILY = 'frame_gap_scaffold'
FAMILIES = (FAMILY,)
LARGEST = 0x400
POSITIONS = 8
_FRAME = re.compile(r'addiu \$sp, \$sp, -(0x[\da-fA-F]+|\d+)')


def gap(rows):
    """Bytes the target's frame is bigger by when every difference is a stack offset, else 0."""
    if not rows or any(marker not in (' ', 's') for marker, _, _ in rows):
        return 0
    frames = [(_FRAME.fullmatch(target or ''), _FRAME.fullmatch(candidate or '')) for _, target, candidate in rows]
    frames = [(want, have) for want, have in frames if want and have]
    if len(frames) != 1:
        return 0
    delta = int(frames[0][0][1], 0) - int(frames[0][1][1], 0)
    return delta if 8 <= delta <= LARGEST and delta % 8 == 0 else 0


def from_rows(source, name, rows):
    size = gap(rows)
    part = view(source, name)
    if not size or not part or re.search(r'\bframe_pad\b', part.clean[part.opening:part.end]):
        return []
    ends = declaration_ends(part)
    indent = re.search(r'\n([ \t]*)\S', source[part.opening:])
    indent = indent.group(1) if indent else '    '
    places = [part.opening + 1] + ends
    if len(places) > POSITIONS:
        step = (len(places) - 1) / (POSITIONS - 1)
        places = [places[round(i * step)] for i in range(POSITIONS)]
    found = []
    for kind, declaration in (('char', f'char frame_pad[{size}];'), ('word', f's32 frame_pad[{size // 4}];')):
        for index, place in enumerate(dict.fromkeys(places)):
            if kind == 'word' and index not in (0, len(places) - 1):
                continue
            text = f'\n{indent}{declaration}'
            found.append((FAMILY, edit(source, [(place, place, text)])))
    return found

