"""One use of a shared address written from a lower symbol: a stack's end, not the buffer that starts there.

Splitters name an address once, but two objects meet there: the end of a thread's stack (`stack + sizeof stack`) is also
where the next buffer starts. Written as one symbol, gcc keeps the address in a saved register and reuses it; the target
builds it again at each use, because the original named two different things. Measured on a 58-instruction N64
device-manager start-up (SN gcc 2.8.1): a queue buffer and `osCreateThread`'s stack argument both `D_x` scored 771, and
120 with the stack argument written `(D_{x - 0x1000} + 0x1000)`.

The family `shared_address_split`: for an `extern` byte array `D_xxxxxxxx[]` the body passes on two or more times, one
child per use with that use alone written as an offset from a lower address-named symbol (declared here), latest use
first (the stack argument comes after the buffer). The linked address is the same: it comes from the symbols' names."""
import re

from .array_address_rebase import _DECL, _edit, _values
from .csource import _blank
from .integer_repair_support import view

FAMILY = 'shared_address_split'
FAMILIES = (FAMILY,)
STEPS = (0x1000, 0x800, 0x400, 0x2000)  # common stack sizes; the first whose symbol the source does not name
LIMIT = 12


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = _blank(source)
    children = []
    for decl in _DECL.finditer(clean):
        symbol, at = decl['name'], int(decl['at'], 16)
        uses = _values(source, clean, part, symbol)
        if len(uses) < 2:
            continue
        for step in STEPS:
            base = f'D_{at - step:08X}'
            if at - step > 0 and not re.search(rf'\b{base}\b', clean, re.I):
                break
        else:
            continue
        for start, end in reversed(uses):
            child = _edit(source, [(start, end, f'({base} + {step:#x})')])
            children.append(child[:decl.start()] + f'extern u8 {base}[];\n' + child[decl.start():])
    return [(FAMILY, child) for child in dict.fromkeys(children)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
