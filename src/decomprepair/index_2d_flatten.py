"""A table declared and read as two-dimensional, written as a flat array indexed `col + row * N`.

`extern u16 T[][24]; ... T[row][col]` and `extern u16 T[]; ... T[col + row * 24]` read the same element, but KMC
GCC 2.7.2 evaluates them differently: the flat form loads `col` first, multiplies `row` and adds `col` last, then
reads with `lui $at; addu; lhu %lo($at)`; the two-dimensional form builds the row's address first. On a 178-instruction
N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O1`) the column-first flat form was exact (1790 -> 0), and the
row-first flat form scored 40.

Offered for a header-less `extern T NAME[][N];` in the source with every use `NAME[a][b]`, giving both operand
orders. A candidate rewrite; the exact judge decides.
"""
import re

from .csource import _blank
from .pattern_repairs import close

FAMILY = 'index_2d_flatten'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
_DECL = re.compile(r'(?m)^(?P<head>[ \t]*extern\s+(?:(?:volatile|const|unsigned|signed|struct)\s+)*' + I + r'[ \t]+\**(?P<name>' +
                   I + r'))\[\]\[(?P<n>0[xX][0-9A-Fa-f]+|\d+)\];')


def _uses(clean, name, source, start):
    """`(from, to, row, col)` of every `name[row][col]` after `start`, or None when a use is another shape."""
    found = []
    for hit in re.finditer(r'\b' + name + r'\b', clean[start:]):
        at = start + hit.start()
        first = start + hit.end()
        row_end = close(clean, first, '[', ']') if clean.startswith('[', first) else None
        col_end = close(clean, row_end, '[', ']') if row_end and clean.startswith('[', row_end) else None
        if not col_end:
            return None
        found.append((at, col_end, source[first + 1:row_end - 1].strip(), source[row_end + 1:col_end - 1].strip()))
    return found


def _term(text):
    return text if re.fullmatch(I + r'|\d+|0[xX][0-9A-Fa-f]+', text) else f'({text})'


def variants(source, name):
    clean = _blank(source)
    result = []
    for decl in _DECL.finditer(clean):
        table, width = decl['name'], decl['n']
        uses = _uses(clean, table, source, decl.end())
        if not uses or any(f'{table}[' in row + col for _, _, row, col in uses):
            continue
        for column_first in (True, False):
            text = source
            for at, to, row, col in reversed(uses):
                scaled = f'{_term(row)} * {width}'
                index = f'{col} + {scaled}' if column_first else f'{scaled} + {_term(col)}'
                text = text[:at] + f'{table}[{index}]' + text[to:]
            flat = source[decl.start('head'):decl.start('name') + len(table)]
            text = text[:decl.start()] + flat + '[];' + text[decl.end():]
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
