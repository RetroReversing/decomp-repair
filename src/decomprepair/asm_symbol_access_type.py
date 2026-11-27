"""Accesses of a table symbol written at the type the target loads and stores it with.

m2c reads and writes a symbol it could not type through its unknown type, as a word: `*(s32 *)((u8 *)&D_8011F328 + o)
= scale * size;` and `*(s32 *)((u8 *)&D_8011F2FD + o) = 2;`, where the target has `swc1 $f0, %lo(D_8011F328)($at)` and
`sb $v1, %lo(D_8011F2FD)($at)`. The compiler then converts the float to an integer (`trunc.w.s`) and stores a word,
and a read of a float table converts the other way (`cvt.s.w`). `asm_symbol_read_width` reads integer load widths
only, and nothing read a store's width or a float access off the target. On a 250-instruction KMC GCC 2.7.2 -O1
object update's machine draft this was the whole of its float and byte rows.

For each symbol the target accesses through `%lo(SYM)` in one class only (all `lwc1`/`swc1`, all `lw`/`sw`, halfword or
byte), every `*(T *)(...)` whose address names that symbol alone is written with the target's type: all the symbols
together first, then each alone. The exact judge decides every child."""
import re

from .asm_symbol_read_width import _apply, _closing, _without_nested_reads
from .csource import _blank, find

FAMILY = 'asm_symbol_access_type'
FAMILIES = (FAMILY,)
LIMIT = 8
_CLASS = {'lwc1': 'float', 'swc1': 'float', 'lw': 'word', 'sw': 'word', 'lh': 'half', 'lhu': 'half', 'sh': 'half',
          'lb': 'byte', 'lbu': 'byte', 'sb': 'byte'}
_SCALAR = r'(?:[su](?:8|16|32)|f32|int|short|char|float|M2C_UNK(?:8|16|32)?|unsigned\s+(?:int|short|char))'
_ACCESS = re.compile(rf'\*\s*(?:\(\s*)?\(\s*(?P<t>{_SCALAR})\s*\*\s*\)\s*(?=\()')


def _types(asm):
    """{symbol: type} for the symbols every `%lo` access treats alike."""
    ops = {}
    for op, sym in re.findall(r'\b(lwc1|swc1|lbu|lb|lhu|lh|lw|sb|sh|sw)\s+\$\w+\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)',
                              asm or ''):
        ops.setdefault(sym, set()).add(op)
    found = {}
    for sym, seen in ops.items():
        classes = {_CLASS[op] for op in seen}
        if len(classes) != 1 or {'lb', 'lbu'} <= seen or {'lh', 'lhu'} <= seen:
            continue
        kind = classes.pop()
        if kind == 'float':
            found[sym] = 'f32'
        elif kind == 'word':
            found[sym] = 's32'
        elif kind == 'half':
            found[sym] = 'u16' if 'lhu' in seen else 's16'
        else:
            found[sym] = 's8' if 'lb' in seen else 'u8'
    return found


def _edits(source, name, types):
    span = find(source, name)
    if not span:
        return {}
    clean = _blank(source)
    found = {}
    for hit in _ACCESS.finditer(clean, span[0], span[1]):
        end = _closing(clean, hit.end())
        if end is None:
            continue
        address = _without_nested_reads(clean[hit.end():end])
        named = [sym for sym in types if re.search(rf'(?<![\w.>]){re.escape(sym)}\b', address)]
        if len(named) != 1:
            continue
        # (a word read as `u32` is already a word: only a change of width or of float-ness is the target's evidence)
        written, wanted = hit['t'], types[named[0]]
        if written == wanted or (wanted == 's32' and written in ('u32', 'int', 'M2C_UNK', 'M2C_UNK32')):
            continue
        found.setdefault(named[0], []).append((*hit.span('t'), wanted))
    return found


def variants(source, name, asm=''):
    found = _edits(source, name, _types(asm))
    out = []
    if len(found) > 1:
        out.append(_apply(source, [edit for edits in found.values() for edit in edits]))
    out += [_apply(source, edits) for _, edits in sorted(found.items())]
    unique = []
    for child in out:
        if child != source and child not in unique:
            unique.append(child)
    return [(FAMILY, child) for child in unique[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
