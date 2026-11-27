"""A plain global read through the nearer global the target's base register holds: `G` as `*(T *)((s8 *)H + k)`.

Two externs the linker puts `k` bytes apart (`D_800AD1E4` and `D_800AD200` = it + 0x1C) are one record the game
declared as the first one: a display-list pointer and, 0x1C bytes on, the state word that goes with it. A function
that reads the second as its own symbol compiles it as `lui; lw %lo(G)`; the game, which wrote the field of the
record it already had a base for, loads `lw $a0, 0x1c($s0)` off the register holding the first symbol's address. An
N64 display-list routine (SN GCC 2.7.2 `-O1`, 250 -> 0): the saved C passed the word to `osVirtualToPhysical` through
the separate symbol, the target through `*(s32 *)((s8 *)D_800AD1E4 + 0x1C)`. Nothing else in the function changed.
The reading of why (hypothesis; the judge decides): cse's related-value lookup folds the symbol-plus-constant address
onto a register that already holds the base's address, and `G` alone is never related to it.

`variants` needs only the names: a scalar integer `extern T D_xxxxxxxx;` (as splat and the draft name them, so the
name says its address) that the function reads, and another `extern ... D_xxxxxxxx` the function also names, at a lower
address within 0x100 bytes. For each such pair it offers each read of `G` alone and then all of its reads together,
spelled `(*(T *)((s8 *)H + 0xK))` (`&H` first when `H` is not an array). A global the project renamed gives no pair:
the address is not in the name.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_read_via_base'
FAMILIES = (FAMILY,)
LIMIT = 12
REACH = 0x100
SCALARS = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'char', 'short', 'long', 'unsigned', 'signed'}
_DNAME = re.compile(r'D_([0-9A-Fa-f]{8})\Z')
_EXTERN = re.compile(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>(?:(?:const|volatile|unsigned|signed)[ \t]+)*{IDENT})'
                     rf'[ \t]+(?P<name>D_[0-9A-Fa-f]{{8}})[ \t]*(?P<array>\[[^\]\n]*\])?[ \t]*;')


def _declared(text):
    """name -> (type text, is an array) of each `extern T D_xxxxxxxx;` / `T D_xxxxxxxx[];`."""
    found = {}
    for hit in _EXTERN.finditer(text):
        if hit['type'] not in {'return', 'goto', 'typedef'}:
            found.setdefault(hit['name'], (' '.join(hit['type'].split()), bool(hit['array'])))
    return found


def _reads(clean, part, name):
    """(start, end) of each use of `name` that is a value (not `&name`, not a member, not `name[`)."""
    uses = []
    for hit in re.finditer(rf'\b{re.escape(name)}\b', clean[part.opening:part.end]):
        start, end = part.opening + hit.start(), part.opening + hit.end()
        before = clean[:start].rstrip()[-2:]
        if before.endswith(('.', '&')) or before == '->' or clean[end:].lstrip().startswith('['):
            continue
        uses.append((start, end))
    return uses


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    types = _declared(clean[:part.opening]) | _declared(re.sub(r'/\*.*?\*/|//[^\n]*', '', header or '', flags=re.S))
    body = clean[part.opening:part.end]
    named = [n for n in dict.fromkeys(re.findall(r'\bD_[0-9A-Fa-f]{8}\b', body)) if n in types]
    result = []
    for target in named:
        kind, array = types[target]
        if array or not all(word in SCALARS for word in kind.split()):
            continue
        uses = _reads(clean, part, target)
        address = int(_DNAME.match(target)[1], 16)
        bases = sorted((address - int(_DNAME.match(n)[1], 16), n) for n in named
                       if n != target and 0 < address - int(_DNAME.match(n)[1], 16) <= REACH)
        for offset, base in bases:
            start = base if types[base][1] else f'&{base}'
            text = f'(*({kind} *)((s8 *){start} + 0x{offset:X}))'
            groups = [[use] for use in uses] + ([uses] if len(uses) > 1 else [])
            for group in groups:
                result.append((FAMILY, edit(source, [(a, b, text) for a, b in group])))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
