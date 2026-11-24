"""The scratch array m2c declares for a function's stack slots is as big as the target's whole frame; the original's was not.

m2c names every stack slot of a function with one scratch array and a macro per slot:

    u8 sp[360];
    #define sp118 (*(s32 *)(sp + 0x118))     /* the target reads 0x118($sp) */

The array is the frame's size and the macros use the target's own `$sp` offsets, so a draft that compiles has three
differences from the original, and each costs rows on its own (a KMC GCC 2.7.2 function with one slot and another with
two: 111 -> 0 on two N64 functions, by hand, in the order 3, 1, 2 below):

1. the array is too big: the compiler reserves `16 + sizeof(sp)` bytes below the saved registers (16 is the outgoing
   argument area of a function that calls), so the frame is bigger than the target's `addiu $sp` and every saved
   register and every slot sits at another offset. The array the original declared ends where its saved registers
   start: its size is the lowest saved register's slot minus the argument area (0x148 = 328 for a target saving at
   0x158 with a 16 byte area; the m2c array was 360);
2. the array starts above the argument area, at `16($sp)`, not at `0($sp)`: a macro that reads `sp + 0x118` reads
   `0x128($sp)`. Every macro's offset is the target's minus that area (`sp + 0x108`);
3. m2c types a slot `s32` when it does not know better, and the target reads it with `lwc1` (a float), `ldc1` (a
   double), or `lw`: an `s32` read of a float slot is compiled with a `cvt.s.w` the target does not have. The type
   follows the instruction the target accesses that offset with.

The target's facts are read from its assembly alone: the frame (`addiu $sp, $sp, -0x168`), the saved registers in the
prologue, the access instruction at each offset a macro names. Children: all three, each pair, each alone (a step that
is worse alone, retyping a slot first, moved 111 -> 11, then the size 11 -> 3, then the rebase 3 -> 0). Proposals only;
the judge decides. Hypothesis, not read from the compiler: GCC 2.7.2 allocates the array right above the argument
area and the saved registers right above the array.
"""
import itertools
import re

from .integer_repair_support import edit, view
from .stack_gap_padding import _ACCESS, _FRAME, _SAVE, argument_area, prologue

FAMILY = 'scratch_frame_array'
FAMILIES = (FAMILY,)
MAXIMUM = 0x2000

_NUMBER = r'(0x[0-9a-fA-F]+|\d+)'
_ARRAY = re.compile(r'(?m)^(?P<head>[ \t]*(?:u8|s8|char|unsigned[ \t]+char)[ \t]+sp\[)(?P<size>0x[0-9a-fA-F]+|\d+)(?P<tail>\][ \t]*;)')
_MACRO = re.compile(r'(?m)^(?P<head>[ \t]*#[ \t]*define[ \t]+sp(?P<name>[0-9A-Fa-f]+)[ \t]+\(\*\()(?P<type>[A-Za-z_][\w ]*?)'
                    r'(?P<mid>[ \t]*\*\)[ \t]*\(sp[ \t]*\+[ \t]*)(?P<offset>0x[0-9A-Fa-f]+|\d+)(?P<tail>\)\))')
_DIRECT = re.compile(r'\bsp[ \t]*\+[ \t]*(?:0x[0-9A-Fa-f]+|\d+)\b')
_INDEXED = re.compile(r'\bsp[ \t]*\[')
_ACCESS_KIND = re.compile(r'\b(?P<op>lw|sw|lwc1|swc1|ldc1|sdc1)\s+\$\w+\s*,\s*' + _NUMBER + r'\(\$sp\)')
_WORD = {'lw': 'int', 'sw': 'int', 'lwc1': 'f32', 'swc1': 'f32', 'ldc1': 'f64', 'sdc1': 'f64'}
_INT4 = {'s32', 'u32', 'int', 'unsigned int', 'long', 'unsigned long', 'M2C_UNK', 'M2C_UNK32'}
_FLOAT4 = {'f32', 'float'}
_INT8 = {'s64', 'u64', 'long long', 'unsigned long long'}


def facts(asm):
    """(frame, lowest saved offset, {offset: access kind}) of the target, or None.

    Kinds: `int` (lw/sw), `f32` (lwc1/swc1), `f64` (ldc1/sdc1) and `addr` for an address taken (`addiu $a0, $sp, N`);
    an offset accessed in two ways has the kind None."""
    frame = _FRAME.search(asm or '')
    saved = [int(m[1], 0) for m in _SAVE.finditer(prologue(asm or ''))]
    if not frame or not saved:
        return None
    kinds = {}
    for hit in _ACCESS_KIND.finditer(asm):
        offset, kind = int(hit[2], 0), _WORD[hit['op']]
        kinds[offset] = kind if kinds.get(offset, kind) == kind else None
    for hit in _ACCESS.finditer(asm):
        offset = int(hit[1] or hit[2], 0)
        if offset not in kinds:
            kinds[offset] = 'addr'
    for offset in saved:
        kinds.pop(offset, None)
    return int(frame[1], 0), min(saved), kinds


def _retyped(current, kind):
    """The type an m2c scalar should have for the access kind, or None when it has it already (or it can't be told)."""
    current = ' '.join(current.split())
    if kind == 'f32':
        return 'f32' if current in _INT4 else None
    if kind == 'int':
        return 's32' if current in _FLOAT4 else None
    if kind == 'f64':
        return 'f64' if current in _INT8 else None
    return None


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    body = part.clean[part.opening:part.end]
    arrays = list(_ARRAY.finditer(part.clean, part.opening, part.end))
    if len(arrays) != 1 or _INDEXED.search(body.replace(arrays[0][0], '', 1)):
        return []
    array = arrays[0]
    found = facts(asm)
    if not found:
        return []
    frame, low_saved, kinds = found
    macros = {int(m['name'], 16): m for m in _MACRO.finditer(source) if re.search(rf'\bsp{m["name"]}\b', body)}
    slots = {offset: m for offset, m in macros.items() if offset in kinds}
    if not slots or max(kinds) >= low_saved or low_saved >= frame:
        return []
    low = min(slots)
    area = argument_area(asm, low)
    size = low_saved - area
    reach = max(offset + (8 if kinds[offset] == 'f64' else 4) for offset in slots) - area
    if size < reach or size % 4 or not 8 <= size <= MAXIMUM or low < area:
        return []
    edits = {}
    if int(array['size'], 0) != size:
        edits['size'] = [(array.start('size'), array.end('size'), str(size))]
    if area and all(int(m['offset'], 0) == offset for offset, m in macros.items()) and not _DIRECT.search(body) \
            and min(macros) >= area:
        edits['rebase'] = [(m.start('offset'), m.end('offset'), f'0x{offset - area:X}') for offset, m in macros.items()]
    typed = [(m.start('type'), m.end('type'), better) for offset, m in slots.items()
             for better in [_retyped(m['type'], kinds[offset]) if kinds[offset] else None] if better]
    if typed:
        edits['retype'] = typed
    names = list(edits)
    return [(FAMILY, edit(source, [change for key in chosen for change in edits[key]]))
            for count in range(len(names), 0, -1) for chosen in itertools.combinations(names, count)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
