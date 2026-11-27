"""A field read through a global's address and an offset, written as the global the game declared at that address.

The inverse of `global_read_via_base`. m2c, which saw one symbol and a constant, writes a halfword at `D_800B84B8 + 2`
as `(*(s16 *)((s8 *)&D_800B84B8 + 2))`; cse then shares one `lui/addiu` of the base for the read and the store, and the
loads and stores take `2($v0)`. The game declared the halfword as its own global (`D_800B84BA`), and the compiler
re-materialises that symbol's address for the read and again for the store (`lui; lh %lo(D_800B84BA)`, `lui; sh`). A
counter at an offset of a lone word, an N64 game's per-frame step (SN GCC 2.7.2 `-O1`, 505 -> 0): the only change was
`D_800B84BA = (s16)((u16)D_800B84BA + 1);` with `extern s16 D_800B84BA;`, in place of the offset spelling of both the
read and the store. (Hypothesis, the judge decides: a `symbol_ref + const` is its own value class in cse, so the base's
register is shared across the two accesses, while the address-named symbol is an operand of the load and store itself.)

`variants` reads `(*(T *)((s8 *)&D_xxxxxxxx + K))` (also `u8`/`char` casts, a base that is an array, `M2C_FIELD(&D_x, T *,
K)` and a negative `K`) for a scalar integer `T`, where the base is named by its address as splat and the draft name
symbols, and offers the sum's address spelled `D_(address + K)`: one child for all the uses of one (address, type), and
one per use when there are several. The extern is added before the function unless that name is already declared; an
existing declaration of another type, or of an array, is never used. Nothing else in the source changes.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'global_offset_symbol'
FAMILIES = (FAMILY,)
LIMIT = 8
REACH = 0x1000
SCALARS = ('s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'char', 'short', 'long')
_NUMBER = r'-?\s*(?:0[xX][0-9A-Fa-f]+|\d+)'
_TYPE = r'(?P<type>(?:unsigned\s+|signed\s+)?(?:' + '|'.join(SCALARS) + r'))'
_BASE = r'&?\s*(?P<base>D_[0-9A-Fa-f]{8})'
_CAST = re.compile(r'\(\s*\*\s*\(\s*' + _TYPE + r'\s*\*\s*\)\s*\(\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*' + _BASE
                   + r'\s*\+\s*(?P<k>\(?\s*' + _NUMBER + r'\s*\)?)\s*\)\s*\)')
_FIELD = re.compile(r'M2C_FIELD\(\s*' + _BASE + r'\s*,\s*' + _TYPE + r'\s*\*\s*,\s*(?P<k>\(?\s*' + _NUMBER
                    + r'\s*\)?)\s*\)')
_EXTERN = re.compile(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>(?:(?:const|volatile|unsigned|signed)[ \t]+)*{IDENT})'
                     rf'[ \t]+(?P<name>D_[0-9A-Fa-f]{{8}})[ \t]*(?P<array>\[[^\]\n]*\])?[ \t]*;')
_ALIAS = {'int': 's32', 'char': 's8', 'short': 's16', 'unsigned char': 'u8', 'unsigned short': 'u16',
          'unsigned int': 'u32', 'unsigned': 'u32', 'signed char': 's8', 'signed short': 's16', 'signed int': 's32',
          'long': 's32'}


def _canon(kind):
    kind = ' '.join(kind.split())
    return _ALIAS.get(kind, kind)


def _declared(text):
    return {hit['name']: (_canon(hit['type']), bool(hit['array'])) for hit in _EXTERN.finditer(text)
            if hit['type'] not in {'return', 'goto', 'typedef'}}


def _number(text):
    return int(re.sub(r'[()\s]', '', text), 0)


def _sites(clean, part):
    """[(start, end, base name, type, offset)] of every spelled access in the function's body."""
    found = []
    for pattern in (_CAST, _FIELD):
        for hit in pattern.finditer(clean, part.opening, part.end):
            found.append((hit.start(), hit.end(), hit['base'], _canon(hit['type']), _number(hit['k'])))
    return sorted(found)


def _declaration_point(clean, name, opening):
    """Where to put a new extern: the start of the line the function's signature begins on."""
    head = list(re.finditer(rf'\b{re.escape(name)}\s*\(', clean[:opening]))
    return clean.rfind('\n', 0, head[-1].start()) + 1 if head else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    known = _declared(clean[:part.opening]) | _declared(re.sub(r'/\*.*?\*/|//[^\n]*', '', header or '', flags=re.S))
    groups = {}
    for start, end, base, kind, offset in _sites(clean, part):
        if base not in known or not offset or abs(offset) > REACH:
            continue
        if _canon(known[base][0]) not in {_canon(t) for t in SCALARS} and not known[base][1]:
            continue
        address = int(base[2:], 16) + offset
        if not 0 <= address <= 0xFFFFFFFF:
            continue
        symbol = f'D_{address:08X}'
        if symbol in known and known[symbol] != (kind, False):
            continue
        groups.setdefault((symbol, kind), []).append((start, end))
    result = []
    for (symbol, kind), uses in groups.items():
        point = None if symbol in known else _declaration_point(clean, name, part.opening)
        if symbol not in known and point is None:
            continue
        choices = ([uses] + [[use] for use in uses]) if len(uses) > 1 else [uses]
        for choice in choices:
            edits = [(a, b, symbol) for a, b in choice]
            if point is not None:
                edits.append((point, point, f'extern {kind} {symbol};\n'))
            result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
