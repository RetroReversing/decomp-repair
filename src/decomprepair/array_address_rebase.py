"""A later address-named byte table written as an offset from an earlier one's base.

Splitters give every address the code names its own symbol, so a long run of calls over one table object reads as
several arrays. GCC 2.7 (KMC, `-O1`) tells them apart: offsets from one array share its base register, and an address
written from that base keeps the base live, which decides which of two held addresses gets a callee-saved register.

Measured on a 1758-instruction N64 spawn list (61 calls): the same calls with the last table as its own symbol scored
10805 (the target holds `base + 0xF0` in a saved register and rebuilds the later table's address at each call; ours did
the reverse), and 0 with that table written `(base + 0x150)`.

The family `array_address_rebase`: for byte arrays `extern u8 D_x[];` used only as values, one child per later array
written from an earlier one within `REACH`, nearest base first, then every later array from the first one. The program
passes the same addresses: the offsets come from the symbols' own names."""
import re

from .csource import _blank
from .integer_repair_support import view

FAMILY = 'array_address_rebase'
FAMILIES = (FAMILY,)
REACH = 0x1000
LIMIT = 40
_DECL = re.compile(r'^[ \t]*extern[ \t]+(?:u8|s8|char|unsigned[ \t]+char|signed[ \t]+char)[ \t]+'
                   r'(?P<name>D_(?P<at>[0-9A-Fa-f]{8}))[ \t]*\[[ \t]*\][ \t]*;', re.M)


def _values(source, clean, part, name):
    """The spans of `name` in the body when every use there passes its address on, else [] (indexed, `&`, `sizeof`)."""
    spans = []
    for hit in re.finditer(rf'(?<![\w.>]){name}\b', part.body):
        before = part.body[:hit.start()].rstrip()
        after = part.body[hit.end():].lstrip()
        if after.startswith('[') or before.endswith('sizeof') or re.search(r'(?<!&)&$|sizeof\s*\($', before):
            return []
        spans.append((part.opening + 1 + hit.start(), part.opening + 1 + hit.end()))
    # a use outside this body (another function, an initialiser) is left as it is, so the symbol is too
    return spans if len(re.findall(rf'\b{name}\b', clean)) == len(spans) + 1 else []


def _edit(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = _blank(source)
    arrays = sorted((int(hit['at'], 16), hit['name']) for hit in _DECL.finditer(clean))
    uses = {symbol: _values(source, clean, part, symbol) for _, symbol in arrays}
    out = []
    for at, symbol in arrays:
        if not uses[symbol]:
            continue
        near = [(base_at, base) for base_at, base in arrays
                if 0 < at - base_at <= REACH and re.search(rf'\b{base}\b', part.body)]
        for base_at, base in sorted(near, reverse=True):
            out.append([(start, end, f'({base} + {at - base_at:#x})') for start, end in uses[symbol]])
    if arrays:
        first_at, first = arrays[0]
        together = [(start, end, f'({first} + {at - first_at:#x})') for at, symbol in arrays[1:]
                    if at - first_at <= REACH for start, end in uses[symbol]]
        if together and re.search(rf'\b{first}\b', part.body):
            out.append(together)
    children = dict.fromkeys(_edit(source, edits) for edits in out)
    return [(FAMILY, child) for child in children if child != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
