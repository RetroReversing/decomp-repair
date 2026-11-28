"""m2c's typed pointer local over byte tables, whose offsets are bytes, declared `char *`.

m2c writes a pointer that two branches set to different tables as `s32 *var_a3;` and then reads through it with byte
offsets, `*(s32 *)((i * 8) + var_a3)`, the way it writes the same reads off the `extern char` symbols themselves. C
scales the sum by the element, so the draft reads `i * 32` bytes along: a wrong program, and `sll $v0, $a1, 5` where
the target has `sll $v0, $a1, 3`. A 170-instruction N64 keyframe routine (SN64 GCC `sn-n64-281`, `-O2 -mfp64`) was
4900 -> 4610 in the isolated judge on this one declaration, and none of 4811 library children offered it.

The child retypes a local `T *v;` (a 2- or 4-byte `T`) to `char *v;` when every value it is given is a byte array
declared in the source (`extern char D[];`) and every other use adds it to a parenthesised offset scaled by a multiple
of the element's size. Any other use (`v[i]`, `*v`, `v->x`, `v += n`) leaves the local alone. `m2cfix.refine_draft`
applies the same retype to a fresh draft. Only MIPS. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'byte_cursor_retype'
FAMILIES = (FAMILY,)
_SIZES = {'s16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4}
_DECLARATION = re.compile(r'(?<=[;{}\n])([ \t]*)(s16|u16|s32|u32|f32) \*([A-Za-z_]\w*);')
_BYTE_ARRAY = re.compile(r'\bextern\s+(?:char|s8|u8)\s+([A-Za-z_]\w*)\s*\[\s*\]\s*;')
_SCALE = re.compile(r'\*\s*(0x[0-9A-Fa-f]+|\d+)\)')


def _byte_use(body, hit, size):
    """Whether the use of the pointer at `hit` is `(... * N ...) + v)` with every N a multiple of `size`."""
    before = body[:hit.start()].rstrip()
    if not body[hit.end():].lstrip().startswith(')') or not before.endswith('+'):
        return False
    offset = before[:-1].rstrip()
    if not offset.endswith(')'):
        return False
    # the statement so far: the scale sits in the offset just before the `+`
    scales = _SCALE.findall(offset[max(offset.rfind(';'), offset.rfind('{')) + 1:])
    return bool(scales) and int(scales[-1], 0) % size == 0


def retyped(source, clean, lo, hi):
    """The declarations between `lo` and `hi` that hold byte offsets: [(start, end, replacement)]."""
    arrays = set(_BYTE_ARRAY.findall(clean))
    out = []
    for declaration in _DECLARATION.finditer(clean, lo, hi):
        size, name = _SIZES[declaration[2]], declaration[3]
        body = clean[declaration.end():hi]
        values, offsets, other = [], 0, 0
        for hit in re.finditer(rf'(?<![\w.>])\b{name}\b', body):
            assigned = re.match(r'\s*=(?!=)\s*([^;]*);', body[hit.end():])
            if assigned and body[:hit.start()].rstrip().endswith((';', '{', '}', ':', ')')):
                values.append(assigned[1].strip())
            elif _byte_use(body, hit, size):
                offsets += 1
            else:
                other += 1
        if values and offsets and not other and all(value in arrays for value in values):
            start, end = declaration.start(2), declaration.end()
            out.append((start, end, f'char *{name};'))
    return out


def apply(source, edits):
    for start, end, replacement in reversed(edits):
        source = source[:start] + replacement + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    edits = retyped(source, clean, opening, span[1])
    return [(FAMILY, apply(source, edits))] if edits else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
