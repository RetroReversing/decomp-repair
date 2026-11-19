"""A field's or a global's type taken from the width and signedness of the target's own loads and stores.

m2c types a field it can't see the declaration of from one use, and a refined draft sometimes keeps a guess: an N64
function read `M2C_FIELD(p, s32 *, 0x10)` where every instruction of the game reading offset 0x10 was `lhu`, and a
global declared `s8` was loaded with `lbu`. gcc's extensions and register choices follow the type, so the rest of the
function drifts with it. Here every `M2C_FIELD(base, T *, OFF)` whose offset the target only ever reads or writes
with one other type, and every `extern T D;` whose `%lo(D)` accesses all have one other type, is given that type.
Offsets the target reaches with several widths (a record's union, a stack slot) are left alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'field_width'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
OPS = {'lb': 's8', 'lbu': 'u8', 'sb': 'u8', 'lh': 's16', 'lhu': 'u16', 'sh': 'u16', 'lw': 's32', 'sw': 's32',
       'lwc1': 'f32', 'swc1': 'f32', 'ldc1': 'f64', 'sdc1': 'f64'}
WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
         'float': 4, 'f64': 8, 'double': 8}
STORE = {'sb', 'sh', 'sw', 'swc1', 'sdc1'}
ACCESS = re.compile(r'\b(lbu|lb|lhu|lh|lwc1|lw|sb|sh|swc1|sw|ldc1|sdc1)\s+\$\w+\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))?\(\s*\$(\w+)\s*\)')
SYMBOL = re.compile(r'\b(lbu|lb|lhu|lh|lwc1|lw|sb|sh|swc1|sw|ldc1|sdc1)\s+\$\w+\s*,\s*%lo\(\s*(' + IDENT + r')\s*\)')


def _offsets(asm):
    """offset -> the C types the target's loads give it (stores only say a width: they count when no load does)."""
    loads, stores = {}, {}
    for op, offset, base in ACCESS.findall(asm or ''):
        if base in ('sp', 'fp', 's8'):
            continue
        at = int(offset, 0) if offset else 0
        (stores if op in STORE else loads).setdefault(at, set()).add(OPS[op])
    return {at: loads.get(at) or stores[at] for at in set(loads) | set(stores)}


def _symbols(asm):
    found = {}
    for op, name in SYMBOL.findall(asm or ''):
        found.setdefault(name, set()).add((OPS[op], op in STORE))
    return {name: {t for t, store in kinds if not store} or {t for t, _ in kinds} for name, kinds in found.items()}


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    offsets = _offsets(asm)
    edits = []
    for m in re.finditer(r'\bM2C_FIELD\s*\(', clean[opening:end]):
        at = opening + m.end()
        stop = close(clean, at - 1)
        if not stop:
            continue
        typed = re.search(r',\s*(?P<type>' + IDENT + r')\s*\*\s*,\s*(?P<off>-?(?:0x[0-9a-fA-F]+|\d+))\s*\)$',
                          clean[at:stop])
        if not typed or typed['type'] not in WIDTH:
            continue
        kinds = offsets.get(int(typed['off'], 0))
        if not kinds or len(kinds) != 1:
            continue
        kind = next(iter(kinds))
        if kind == typed['type'] or (WIDTH[kind] == WIDTH[typed['type']] and kind[0] == typed['type'][0]):
            continue
        edits.append((at + typed.start('type'), at + typed.end('type'), kind))
    symbols = _symbols(asm)
    # (retyped where it's used: the project's header declares the global too, and a second, different declaration
    # doesn't compile)
    declared = {m['name']: m['type'] for m in
                re.finditer(r'(?m)^[ \t]*extern\s+(?P<type>' + IDENT + r')\s+(?P<name>' + IDENT + r')\s*;', clean)
                if not span[0] <= m.start() < span[1]}
    for symbol, was in declared.items():
        kinds = symbols.get(symbol)
        if was not in WIDTH or not kinds or len(kinds) != 1:
            continue
        kind = next(iter(kinds))
        if kind == was or (was == 'char' and kind in ('s8', 'u8')):
            continue
        for m in re.finditer(r'(?<![\w.>&])' + re.escape(symbol) + r'\b(?!\s*\()', clean[opening:end]):
            at = opening + m.start()
            edits.append((at, at + len(symbol), f'(*({kind} *)&{symbol})'))
    if not edits:
        return []

    def apply(chosen):
        text = source
        for a, b, kind in sorted(chosen, reverse=True):
            text = text[:a] + kind + text[b:]
        return text
    result = [(FAMILY, apply(edits))]
    if len(edits) > 1:
        result += [(FAMILY, apply([e])) for e in edits[:5]]
    return result
