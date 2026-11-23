"""A narrow signed parameter masked with `& 0xFFFF` or `& 0xFF`, written as the unsigned cast.

For `s16 id`, `id & 0xFFFF` is `(sign_extend id) & 0xFFFF` to gcc 2.7.2: cse looks the extension up and, when another use of
`id` already computed it (a table index, a `(s16) id` argument), reads the mask from that register
(`andi $s0, $s0, 0xffff`) and leaves the extension with two uses, so combine cannot fold `sra 16; sll 2` into one `sra 14`
for the index. `(u16) id` is a zero extension of the parameter register itself, and the target's `andi $s0, $s7, 0xffff` reads
`$s7` directly. In a 795-instruction N64 object spawner whose first parameter is an `s16` that took 1245 -> 690, the whole
difference of the table-index shifts, the masks' registers and the cse-shared extension (the saved best, with the width
and the casts as m2c had them, was 3693). The reading of cse.c and combine.c is a hypothesis; the judge decides.

The shape: a function whose parameter is a signed halfword (`s16`, `short`, `signed short`) or a signed byte (`s8`, `signed
char`) and that masks it, as a whole operand, with `0xFFFF` / `0xFF` (either side of the `&`). One child rewrites every
`& 0xFFFF` mask as `(u16) id`; one every `& 0xFF` as `(u8) id`; one both.
"""
import re

from .arm_block_support import IDENT
from .integer_repair_support import edit, view

FAMILY = 'narrow_param_mask_cast'
FAMILIES = (FAMILY,)

SIGNED16 = r'(?:s16|short|signed\s+short(?:\s+int)?)'
SIGNED8 = r'(?:s8|signed\s+char)'


def _parameters(clean, opening):
    """{name: bit width} for the signed narrow parameters of the definition whose body opens at `opening`."""
    head = clean[:opening]
    start = head.rfind('(', 0, head.rfind(')') + 1)
    found = {}
    for part in head[start + 1:head.rfind(')')].split(','):
        hit = re.fullmatch(rf'\s*({SIGNED16}|{SIGNED8})\s+({IDENT})\s*', part)
        if hit:
            found[hit[2]] = 16 if re.fullmatch(SIGNED16, hit[1]) else 8
    return found


def _sites(body, base, name, literal):
    out = []
    number = re.escape(literal)
    for hit in re.finditer(rf'(?<![\w.>\]])({re.escape(name)})\s*&\s*{number}\b(?!\s*[\w(])|(?<![\w])0x{literal[2:]}\s*&\s*({re.escape(name)})\b', body, re.I):
        out.append((base + hit.start(), base + hit.end()))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    params = _parameters(clean, part.opening)
    if not params:
        return []
    body = clean[part.opening:part.end]
    halves, bytes_ = [], []
    for param, width in params.items():
        if width == 16:
            halves += [(a, b, param, 'u16') for a, b in _sites(body, part.opening, param, '0xFFFF')]
        bytes_ += [(a, b, param, 'u8') for a, b in _sites(body, part.opening, param, '0xFF')]
    groups = [halves, bytes_, halves + bytes_]
    out = []
    for group in groups:
        if not group:
            continue
        text = edit(source, [(a, b, f'({cast}) {param}') for a, b, param, cast in group])
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # the registry: no caller wiring (registry.py)
