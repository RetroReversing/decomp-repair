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


_RECORD_WIDTHS = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4}
_RECORD_ACCESS = {1: 'sb|lb|lbu', 2: 'sh|lh|lhu', 4: 'sw|lw'}
_RECORD_DECL = re.compile(
    r'(?m)^[ \t]*(?P<kind>s8|u8|s16|u16|s32|u32)[ \t]+(?P<name>sp(?P<off>[0-9A-Fa-f]+));[ \t]*$'
)
_STACK_ADDRESS = re.compile(r'\baddiu\s+\$a[0-3]\s*,\s*\$sp\s*,\s*(0x[0-9a-fA-F]+|\d+)\b')


def record_variants(source, name, asm, header=''):
    """Keep the scalar prefix of an address-taken stack record at its measured offset."""
    from .integer_repair_support import edit, view

    if not asm or not (addresses := {int(text, 0) for text in _STACK_ADDRESS.findall(asm)}):
        return []
    floor = saved_floor(asm)
    if floor is None or not (part := view(source, name)):
        return []
    if any(token in source + header for token in ('__repair_record_prefix', '__repair_record_bytes')):
        return []
    start = part.opening + 1
    result = []
    declarations = list(_RECORD_DECL.finditer(part.body))
    for decl in declarations:
        offset = int(decl['off'], 16)
        kind, local = decl['kind'], decl['name']
        width = _RECORD_WIDTHS[kind]
        if offset not in addresses or offset >= floor or offset % width:
            continue
        previous = part.body[:decl.start()]
        if previous.count('{') != previous.count('}'):
            continue
        # Other stack views are possible barriers even when this rule cannot rewrite them.
        slots = {int(value, 16) for value in re.findall(r'\bsp([0-9A-Fa-f]+)\b', part.body)}
        stop = min((other for other in slots if offset < other < floor), default=floor)
        size = stop - offset
        access = re.compile(rf'\b(?:{_RECORD_ACCESS[width]})\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
        if size % width or not width < size <= 128 or offset not in {int(m, 0) for m in access.findall(asm)}:
            continue
        token = re.compile(rf'\b{local}\b')
        if re.search(rf'(?m)^\s*#\s*define\s+{local}\b', header + '\n' + part.clean):
            continue
        uses = list(token.finditer(part.body))
        if len(uses) < 3 or not re.search(rf'&\s*{local}\b', part.body):
            continue
        if any(re.search(r'(?:\.|->)\s*$', part.body[:use.start()]) for use in uses):
            continue
        if len(re.findall(rf'\b[A-Za-z_]\w*\s+\**{local}\s*(?=[;=,\[])', part.body)) != 1:
            continue
        new = f'struct {{ {kind} __repair_record_prefix; u8 __repair_record_bytes[{size-width}]; }} {local};'
        edits = [(start+decl.start('kind'), start+decl.end(), new)]
        edits.extend((start+hit.start(), start+hit.end(), f'{local}.__repair_record_prefix')
                     for hit in uses if hit.start() != decl.start('name'))
        result.append(('stack_record_extent', edit(source, edits)))
        if len(result) >= 4:
            break
    return result
