"""A wide local loaded from a byte member, read later as the byte it holds: `(u8) v` at the reads after the first.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 200 with one differing
instruction: a record's byte scale was read into a local, multiplied by a row height (the product takes the loaded
register as it is) and used twice more, in a compare against `top - scale` and in `top + scale * limit`. The target
masks the byte once for those two reads (`andi $a1,$v1,0xff`) and keeps the unmasked load for the product; every
spelling that changed the local's type (`u8`, `u16`, a second `t` local, a multi-set temporary) either folded the mask
into a plain move or left the product on the masked copy. The local left as `s32` with a `(u8)` cast on each of its later
reads was exact (200 -> 0).

byte_read_casts
    `v = P->f;` (v a wide local, f a `u8` member of the visible record) followed by reads of `v` becomes the same with
    `(u8) v` at every read after the first, and, as a second child, at every read. The cast never changes the value (the
    local only ever holds a byte). Offered only when `v` is assigned exactly once and is never written otherwise
    (no `++`, no compound assignment, no address taken). Hypothesis from the match, not from the compiler source: the
    first read keeps the load's own extension, and each later `(u8)` is a `zero_extend` of a narrower view of the same
    pseudo that combine keeps when the pseudo is read through both views.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_read_casts'
FAMILIES = (FAMILY,)
LIMIT = 4
_WIDE = r'(?:s32|u32|int|unsigned(?:\s+int)?|signed(?:\s+int)?)'
_BYTE = r'(?:u8|unsigned\s+char)'
_ASSIGN = re.compile(rf'(?P<v>{IDENT})\s*=\s*(?P<base>{IDENT})\s*->\s*(?P<field>{IDENT})\s*;')


def _names(text, name):
    return [m for m in re.finditer(rf'\b{re.escape(name)}\b', text) if not re.search(r'(?:->|\.)\s*$', text[:m.start()])]


def _byte_field(context, field):
    for hit in re.finditer(rf'\b(?P<type>{_BYTE})\s+(?P<names>[^;{{}}]*\b{re.escape(field)}\b[^;{{}}]*);', context):
        return True
    return False


def _wide_local(part, v):
    return re.search(rf'(?m)^[ \t]*{_WIDE}\s+(?:{IDENT}\s*,\s*)*{re.escape(v)}\b(?:\s*,\s*{IDENT})*\s*;', part.clean[part.opening + 1:part.end])


def _children(source, name, header):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    context = _blank(header) + '\n' + _blank(source)
    clean, result = part.clean, []
    body_start = part.opening + 1
    for assign in _ASSIGN.finditer(clean, body_start, part.end):
        v = assign['v']
        if not _wide_local(part, v) or not _byte_field(context, assign['field']):
            continue
        occurrences = _names(clean[body_start:part.end], v)
        writes = [m for m in occurrences if re.match(r'\s*(?:\+\+|--|[-+*/&|^<>]*=(?!=))', clean[body_start + m.end():])
                  or re.search(r'(?:\+\+|--|&)\s*$', clean[:body_start + m.start()])]
        if len(writes) != 1 or body_start + writes[0].start() != assign.start('v'):
            continue
        declared = _wide_local(part, v)
        reads = [m for m in occurrences if body_start + m.start() >= assign.end() and m is not writes[0]
                 and not (declared.start() <= m.start() < declared.end())]
        reads = [m for m in reads if m.start() >= assign.end() - body_start]
        if len(reads) < 2:
            continue
        for chosen in (reads[1:], reads):
            edits = [(body_start + m.start(), body_start + m.end(), f'(u8){v}') for m in chosen]
            result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


def variants(source, name, header=''):
    return _children(source, name, header)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
