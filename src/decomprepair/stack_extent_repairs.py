"""A stack object m2c declared as one scalar, sized as the target's frame lays it out.

m2c names a stack object by its offset (`sp30`) and types it by the first access it sees, so a buffer handed to a
call (`sprintf(&sp30, ...)`) becomes `s32 sp30;`. The game's frame says how big it is: the next thing the target
keeps on the stack (a saved register, another object whose address it takes) starts where it ends. An N64 function
had a 0x58-byte frame where the draft's was 0x40; with `char sp30[0x20]` (0x30 up to `$s0` saved at 0x50) the frame
was right and it went from 66 to 60. Offered only when every use takes the object's address.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stack_object_extent'
FAMILIES = (FAMILY,)

SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'M2C_UNK': 4, 's64': 8,
         'u64': 8, 'f64': 8}
DECLARATION = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*(?:\s*\*)?)\s+(?P<name>sp(?P<offset>[0-9A-Fa-f]+))'
                         r'\s*;[ \t]*\n')
SLOT = re.compile(r'\b(?:sw|sd|sdc1|swc1|sh|sb)\s+\$\w+\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\(\$sp\)')
ADDRESS = re.compile(r'\baddiu\s+\$\w+\s*,\s*\$sp\s*,\s*(0x[0-9a-fA-F]+|\d+)')


def stack_marks(asm):
    """Offsets the target stores to or takes the address of, relative to its own stack pointer."""
    marks = {int(m[1], 0) for m in SLOT.finditer(asm or '')}
    marks |= {int(m[1], 0) for m in ADDRESS.finditer(asm or '')}
    return sorted(marks)


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    marks = stack_marks(asm)
    result = []
    for hit in DECLARATION.finditer(clean, opening, end):
        var, offset = hit['name'], int(hit['offset'], 16)
        kind = hit['type'].strip()
        size = 4 if kind.endswith('*') else SIZES.get(kind)
        if size is None:
            continue
        uses = [m for m in re.finditer(r'\b' + var + r'\b', clean[hit.end():end])]
        # every use takes its address (a buffer, or a record filled through a pointer)
        if not uses or any(not re.search(r'&\s*$', clean[:hit.end() + m.start()]) for m in uses):
            continue
        later = [m for m in marks if m > offset]
        if not later:
            continue
        extent = later[0] - offset
        if extent <= size or extent > 0x400:
            continue
        body = source[hit.end():end]
        body = re.sub(r'&\s*\b' + var + r'\b', var, body)
        for written in (f'char {var}[0x{extent:X}];', f'{kind} {var}[{max(1, extent // size)}];' if size > 1 else None):
            if not written:
                continue
            text = source[:hit.start()] + hit['indent'] + written + '\n' + body + source[end:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:4]
