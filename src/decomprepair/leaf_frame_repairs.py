"""A leaf's unused stack frame, and narrow locals the target never sign-extends.

An N64 leaf function opens a frame, `addiu $sp, $sp, -8`, and never stores to it: the source had a local array it
never used, which gcc 2.7.2 still reserves. m2c drops unused locals, so the draft builds no frame; an unused
`u8 __repair_frame[8];` gives it back (`unused_frame_local`). The same function masked a byte with `1 << n` held in an
`s8`, which gcc sign-extends (`sll`/`sra` by 24) before the `and`; the target has no such pair, and as a `u8` it was
exact (`unsigned_narrow_local`, each narrow signed local alone and all together, only when the target sign-extends
nothing of that width).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FRAME = 'unused_frame_local'
UNSIGNED = 'unsigned_narrow_local'
FAMILIES = (FRAME, UNSIGNED)

IDENT = r'[A-Za-z_]\w*'


def _frame(asm):
    """The frame size when the target opens one and never stores to it or calls (a leaf), else None."""
    opened = re.search(r'\baddiu\s+\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)', asm or '')
    if not opened or re.search(r'\b(?:sw|sh|sb|sd|swc1|sdc1)\s+\$\w+\s*,\s*-?(?:0x[0-9a-fA-F]+|\d+)?\(\$sp\)', asm) \
            or re.search(r'\bjal\b|\bjalr\b', asm):
        return None
    return int(opened[1], 0)


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    result = []
    size = _frame(asm)
    if size and '__repair_frame' not in clean:
        at = opening + 1
        result.append((FRAME, source[:at] + f'\n    u8 __repair_frame[{size}];' + source[at:]))
    for kind, wide, shift, load in (('s8', 'u8', 0x18, 'lb'), ('s16', 'u16', 0x10, 'lh')):
        # (the target sign-extends values of that width somewhere, by shifts or a signed load: leave them signed)
        if re.search(r'\bsra\s+\$\w+\s*,\s*\$\w+\s*,\s*' + hex(shift) + r'\b', asm) or re.search(r'\b' + load + r'\s', asm):
            continue
        locals_ = list(re.finditer(r'(?m)^([ \t]*)' + kind + r'(\s+' + IDENT + r'\s*;)', body))
        edits = []
        for m in locals_:
            at = opening + m.start() + len(m[1])
            edits.append(at)
            result.append((UNSIGNED, source[:at] + wide + source[at + len(kind):]))
        if len(edits) > 1:
            text = source
            for at in reversed(edits):
                text = text[:at] + wide + text[at + len(kind):]
            result.append((UNSIGNED, text))
    return result[:6]
