"""Two stack slots whose addresses a function passes on, with a frame pad between them: one byte buffer.

m2c names each stack object it saw an address of (`M2C_UNK sp18;`, `M2C_UNK sp5C;`), and a search that wanted the
frame's size declared a pad between them (`char frame_pad[504];`). The pad puts the second slot at the bottom of
the frame (offsets 0x210 and 0x214 against the target's 0x18 and 0x5C: score 2 on a KMC GCC 2.7.2 N64 function,
0x220 frame), and separate arrays put it elsewhere (score 1). The game declared one buffer and handed out two
places in it:

    u8 buf[512];
    f(arg1, arg2, arg3, 0, 0, (M2C_UNK *) buf);   g(arg0, (M2C_UNK *) (buf + 0x44));

with the distance between the slots the `spNN` offsets' difference (0x5C - 0x18). The size is every declaration of
the block added up (the two words and the pad: 4 + 504 + 4), rounded up to 8, so the frame stays what the pad made
it. Offered only when a pad is declared (no pad: the size would need the target's frame, which the callers of
`stack_gap_padding` supply), at least two scalar word locals are only ever used as `&spNN`, and nothing reads or
assigns them. A candidate for the judge; a hypothesis about the game's object, not read from the compiler.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stack_slots_one_buffer'
FAMILIES = (FAMILY,)
MAXIMUM = 0x1000

_WORDS = {'s32', 'u32', 'M2C_UNK', 'M2C_UNK32', 'int', 'unsigned', 'long'}
_DECL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*?)[ \t]+'
                   r'sp(?P<off>[0-9A-Fa-f]+)[ \t]*;[ \t]*\n')
_PAD = re.compile(r'(?m)^[ \t]*(?:char|u8|s8)[ \t]+(?:frame_pad|pad\w*)\[(?P<size>\d+)\];[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    pads = list(_PAD.finditer(body))
    slots = [m for m in _DECL.finditer(body) if ' '.join(m['type'].split()) in _WORDS]
    if len(pads) != 1 or len(slots) < 2:
        return []
    bare = body
    for m in [*slots, *pads]:
        bare = bare[:m.start()] + re.sub(r'\S', ' ', m[0]) + bare[m.end():]
    uses = []
    for m in slots:
        found = list(re.finditer(r'(?<![\w.>])sp' + m['off'] + r'\b', bare))
        if not found or any(not re.search(r'&\s*$', bare[:u.start()]) for u in found):
            return []
        uses.append(found)
    order = sorted(slots, key=lambda m: int(m['off'], 16))
    first = int(order[0]['off'], 16)
    size = 4 * len(slots) + int(pads[0]['size'])
    size = (size + 7) & ~7
    if size > MAXIMUM:
        return []
    buf = 'sp' + order[0]['off'] + '_buf'
    edits = [(opening + m.start(), opening + m.end(), '') for m in [*slots, *pads]]
    anchor = min(m.start() for m in [*slots, *pads])
    edits.append((opening + anchor, opening + anchor,
                  f"{slots[0]['indent']}u8 {buf}[{size}];\n"))
    for m, found in zip(slots, uses):
        delta = int(m['off'], 16) - first
        cast = ' '.join(m['type'].split()) + ' *'
        place = buf if not delta else f'{buf} + 0x{delta:X}'
        for u in found:
            amp = bare.rfind('&', 0, u.start())
            edits.append((opening + amp, opening + u.end(), f'({cast}) ({place})' if delta else f'({cast}) {buf}'))
    text = source
    for a, b, rep in sorted(set(edits), key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:a] + rep + text[b:]
    return [(FAMILY, text)] if text != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
