"""A `static inline` helper's integer parameter declared at another width (`u32 value` as `u16`, `u8`, `s16` or `s32`).

KMC GCC 2.7.2 (`-O2`, N64) inlines the helper by copying each argument into a pseudo of the parameter's mode
(integrate.c); MIPS defines no PROMOTE_MODE, so a `u16` parameter is a halfword pseudo whose conversion from the
caller's expression is a separate insn, and the first scheduler places it by the parameter's uses, not where the
caller computed the value. A sound-sequence interpreter's branch helper (`value >= D_9E` then a table lookup) called
with `randomU16Next() & 0xFF` and with halfword fields: with `u16 value` the `andi` of the masked argument comes after
the helper's own loads (`lbu; lw; andi; sltu`), as the target has it, where `u32 value` put it first. 3350 -> 3230 on
a 1315-instruction function. The judge decides; the program is the same when every caller passes a value that fits,
which a width the callers' expressions are already masked or loaded at is.

Offers, for each scalar integer parameter of each `static inline` function in the source, each other width of
`u8 u16 s16 u32 s32`, one parameter at a time. Bounded to `LIMIT` children.
"""
import re

from .integer_repair_support import IDENT

FAMILY = 'inline_param_width'
FAMILIES = (FAMILY,)
LIMIT = 16
WIDTHS = ('u16', 'u8', 's16', 'u32', 's32')
_HEAD = re.compile(rf'(?m)^[ \t]*(?:static\s+inline|inline\s+static)\s+[^;{{()]*?\b(?P<fn>{IDENT})\s*\((?P<params>[^)]*)\)\s*\{{')


def variants(source, name, header=''):
    out = []
    for head in _HEAD.finditer(source):
        if head['fn'] == name:
            continue
        params_start = head.start('params')
        offset = 0
        for piece in head['params'].split(','):
            found = re.fullmatch(rf'(\s*)(u8|u16|s16|u32|s32|int|unsigned int)(\s+)({IDENT})(\s*)', piece)
            if found:
                start = params_start + offset + found.start(2)
                end = params_start + offset + found.end(2)
                for width in WIDTHS:
                    if width != found.group(2):
                        out.append((FAMILY, source[:start] + width + source[end:]))
            offset += len(piece) + 1
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
