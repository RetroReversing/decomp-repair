"""Stack objects as big as the target's frame says they are.

m2c names a local whose address is taken after its offset, `M2C_UNK sp18;`, and gives it a word. When it is really
a buffer (a matrix, a message, a 512-byte scratch area) the frame comes out too small and every saved register moves:
an N64 function's frame was 0x30 where the game's was 0x228. The target's own prologue bounds each object: it runs up
to the next object's offset, or to the lowest slot a saved register takes. Declared as `u8 spNN[size]`, its address
taken as before, the frames matched (four N64 functions exact, one of them also dropping a padding array an earlier
repair had added in its place).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stack_object_size'
FAMILIES = (FAMILY,)

FRAME = re.compile(r'\baddiu\s+\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)')
SAVED = re.compile(r'\b(?:sw|sd|sdc1)\s+\$(?:s\d|ra|fp|f2\d|f3\d)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
PADDING = re.compile(r'(?m)^[ \t]*(?:/\*[^*]*\*/[ \t]*\n[ \t]*)?char\s+__repair_stack_padding\s*\[[^]]*\]\s*;[ \t]*\n')


def saved_floor(asm):
    """The lowest stack offset the target's prologue saves a register at (None without a frame)."""
    lines = (asm or '').splitlines()
    for i, line in enumerate(lines):
        if FRAME.search(line):
            slots = [int(m[1], 0) for m in map(SAVED.search, lines[i:i + 24]) if m]
            return min(slots) if slots else int(FRAME.search(line)[1], 0)
    return None


def variants(source, name, asm):
    span = find(source, name)
    floor = saved_floor(asm)
    if not span or floor is None:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    declared = {m['name']: m for m in re.finditer(
        r'(?m)^[ \t]*(?P<type>[A-Za-z_][\w ]*?)\s+(?P<name>sp(?P<off>[0-9A-Fa-f]+))\s*;[ \t]*\n', body)}
    if not declared:
        return []
    offsets = sorted((int(m['off'], 16), n) for n, m in declared.items())
    edits = []
    for i, (offset, local) in enumerate(offsets):
        bound = offsets[i + 1][0] if i + 1 < len(offsets) else floor
        size = bound - offset
        uses = re.findall(r'(&\s*)?\b' + local + r'\b', body)
        # only objects used by address alone, and bigger than the word m2c gave them
        if size <= 4 or len(uses) < 2 or any(not amp for amp in uses[1:]):
            continue
        decl = declared[local]
        edits.append((opening + decl.start('type'), opening + decl.end('name'), f'u8 {local}[0x{size:X}]'))
        edits += [(opening + m.start(), opening + m.end(), local)
                  for m in re.finditer(r'&\s*' + local + r'\b', body)]
    if not edits:
        return []
    text = source
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    result = [(FAMILY, text)]
    stripped = PADDING.sub('', text, count=1)
    if stripped != text:
        result.insert(0, (FAMILY, stripped))
    return result
