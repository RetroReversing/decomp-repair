"""A stack object m2c declared as one scalar, sized as the target's frame lays it out.

m2c names a stack object by its offset (`sp30`) and types it by the first access it sees, so a buffer handed to a
call (`sprintf(&sp30, ...)`) becomes `s32 sp30;`. The game's frame says how big it is: the next thing the target
keeps on the stack (a saved register, another object whose address it takes) starts where it ends. An N64 function
had a 0x58-byte frame where the draft's was 0x40; with `char sp30[0x20]` (0x30 up to `$s0` saved at 0x50) the frame
was right and it went from 66 to 60. A byte buffer is often read as a value too (`strcpy(&sp50, name); if (sp50 != 0)`): when a byte scalar has its
address taken and is also read or written, one child declares `kind spXX[n]` and writes those uses `spXX[0]`. An N64
asset loader (sn-n64-281) whose file name buffer m2c declared `u8 sp50` went 132 -> 0 with `u8 sp50[0x20]`.
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
UNARY = re.compile(r'(?:[=(,?:{};)]|\breturn)\s*&\s*$')
BYTES = {'s8', 'u8', 'char'}


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
        taken = [bool(re.search(r'&\s*$', clean[:hit.end() + m.start()])) for m in uses]
        if not uses or not any(taken):
            continue
        values = [] if all(taken) else [m for m in uses if not UNARY.search(clean[:hit.end() + m.start()])]
        if values and (kind not in BYTES or any(re.match(r'\s*(?:\.|\[|->|\()', clean[hit.end() + m.end():])
                                                  or re.search(r'&\s*$', clean[:hit.end() + m.start()])
                                                  for m in values)):
            continue
        later = [m for m in marks if m > offset]
        if not later:
            continue
        extent = later[0] - offset
        if extent <= size or extent > 0x400:
            continue
        body = source[hit.end():end]
        typed = f'{kind} {var}[{max(1, extent // size)}];'
        if values:  # from the back, so earlier offsets stay good
            for m in reversed(values):
                body = body[:m.end()] + '[0]' + body[m.end():]
            shapes = (typed,)
        else:
            shapes = (f'char {var}[0x{extent:X}];', typed if size > 1 else None)
        body = re.sub(r'&\s*\b' + var + r'\b', var, body)
        for written in shapes:
            if not written:
                continue
            text = source[:hit.start()] + hit['indent'] + written + '\n' + body + source[end:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:4]
