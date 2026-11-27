"""m2c's `*(s32 *)((i * 2) + ((row * 0x12C) + &D_X))` written back as the two-dimensional table: `D_X[row][i]`.

m2c types an address-named table `M2C_UNK`, casts every access `s32 *` and adds the byte offsets to the symbol, and it
names a row reached with a constant index by its own address (`&D_X + 0x12C`, or the symbol linked there). The rows,
the columns and the element's width are all in the arithmetic: the larger scale is the row's size and the smaller one
the element's.

    extern M2C_UNK D_80100000;                       extern u16 D_80100000[][150];
    extern M2C_UNK D_8010012C;
    *(s32 *)((n * 2) + ((r * 0x12C) + &D_80100000))  ->  D_80100000[r][n]
    *(&D_80100000 + (n * 2))                             D_80100000[0][n]
    *(s32 *)((n * 2) + &D_8010012C)                      D_80100000[1][n]

A byte offset m2c carries beside a loop counter (`off = 0 * 2; ... i += 1; off = i * 2;`) is read as the counter times
the element size (indexed_symbol_records' reading). Shift spellings of a row's size (`<< 5`) count. Every table of the
function is converted together, with unsigned and then signed elements.

A 119-instruction N64 list builder (KMC GCC 2.7.2) scored 7260 from its draft under `-O1`; with its two tables
declared this way the draft scored 1430, and the repair chain reaches 400 from the form that keeps m2c's offsets.

Nothing is rewritten unless every use of every symbol of a table is one of these accesses.
"""
import re

from .csource import _blank, find
from .indexed_symbol_records import _ACCESS, _SYMBOL, _offset_temps, _terms, _wrapped
from .pattern_repairs import close

FAMILY = 'symbol_row_arrays'
FAMILIES = (FAMILY,)
MAX_ROW = 16  # a symbol further than this many rows from the table is another table
_TYPES = {1: ('u8', 's8'), 2: ('u16', 's16'), 4: ('u32', 's32')}
_SHIFT = re.compile(r'<<[ \t]*([1-9]|1[0-5])\b')


def _accesses(body, temps):
    """[(start, end, symbol, address, [(index, scale)])] of every dereference of one symbol's sum."""
    found = []
    for m in _ACCESS.finditer(body):
        opening = body.find('(', m.end() - 1 if body[m.end() - 1] == '(' else m.end())
        if opening < 0:
            continue
        stop = close(body, opening, '(', ')')
        if not stop:
            continue
        inner = body[opening + 1:stop - 1]
        nested = re.fullmatch(r'\s*\(\s*[A-Za-z_]\w*\s*\*\s*\)\s*(\(.*\))\s*', inner, re.S)
        if m['type'] is None and nested and _wrapped(nested[1]):
            inner = nested[1][1:-1]
        if not re.search(r'\b' + _SYMBOL + r'\b', inner):
            continue
        terms = _terms(_SHIFT.sub(lambda s: f'* {1 << int(s[1])}', inner), temps, m.start())
        if terms is None or len(terms[0]) != 1 or not terms[2]:
            continue
        symbol = terms[0][0]
        found.append((m.start(), stop, symbol, int(symbol[2:], 16) + terms[1], terms[2]))
    return found


def _tables(accesses):
    """[(base address, row size, element size)] of the symbols indexed by two scales, one a multiple of the other."""
    scales = {}
    for _, _, symbol, _, indices in accesses:
        scales.setdefault(symbol, set()).update(scale for _, scale in indices)
    tables = []
    for symbol, found in sorted(scales.items()):
        stride = max(found)
        sizes = [s for s in _TYPES if s < stride and not stride % s and found <= {s, stride}]
        small = [s for s in sizes if s in found]
        if len(small) == 1 and stride >= 8:
            tables.append((int(symbol[2:], 16), stride, small[0]))
    return tables


def _place(address, indices, table):
    """(row text, column text) of an access to `table`, or None."""
    base, stride, size = table
    offset = address - base
    outer = [i for i, scale in indices if scale == stride]
    inner = [i for i, scale in indices if scale == size]
    if offset < 0 or offset % size or len(outer) > 1 or len(inner) > 1 or len(outer) + len(inner) != len(indices):
        return None
    rows, column = divmod(offset, stride)
    column //= size
    if rows > MAX_ROW or (outer and rows):
        return None
    row = outer[0] if outer else str(rows)
    if not inner:
        return row, str(column)
    return row, f'{inner[0]} + {column}' if column else inner[0]


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    head, tail = source[:span[0]], source[span[1]:]
    original = source[span[0]:span[1]]
    original, _ = _offset_temps(original, _blank(original))
    body = _blank(original)
    temps = {}
    for m in re.finditer(r'(?m)^[ \t]*([A-Za-z_]\w*)\s*=\s*([^=;][^;]*);', body):
        temps.setdefault(m[1], []).append((m.start(), m[2].strip()))
    accesses = _accesses(body, temps)
    edits, used = [], []
    for table in _tables(accesses):
        base, stride, size = table
        rows = f'D_{base:08X}'
        mine, symbols = [], {rows}
        for a, b, symbol, address, indices in accesses:
            # the table's own symbol, or one linked at the start of a later row and indexed by the column only
            later = int(symbol[2:], 16) - base
            if symbol != rows and not (0 < later <= MAX_ROW * stride and not later % stride
                                       and all(scale == size for _, scale in indices)):
                continue
            place = _place(address, indices, table)
            if place is None:
                mine = []
                break
            mine.append((a, b, f'{rows}[{place[0]}][{place[1]}]'))
            symbols.add(symbol)
        if not mine or any(re.search(r'\b' + s + r'\b', header) for s in symbols):
            continue
        left = body
        for a, b, _ in mine:
            left = left[:a] + ' ' * (b - a) + left[b:]
        if any(re.search(r'\b' + s + r'\b', left) for s in symbols):
            continue
        edits += mine
        used.append((rows, symbols, stride // size, size))
    edits.sort()
    if not used or any(first[1] > second[0] for first, second in zip(edits, edits[1:])):
        return []
    text = original
    for a, b, replacement in reversed(edits):
        text = text[:a] + replacement + text[b:]
    # the temporaries that only carried an offset or a row's product
    for temp in temps:
        uses = len(re.findall(r'\b' + temp + r'\b', _blank(text)))
        assigned = len(re.findall(r'(?m)^[ \t]*' + temp + r'\s*=[^=;][^;]*;[ \t]*\n', text))
        declared = re.search(r'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+' + temp + r'\s*;[ \t]*\n', text)
        if assigned and declared and uses == assigned + 1:
            text = re.sub(r'(?m)^[ \t]*' + temp + r'\s*=[^=;][^;]*;[ \t]*\n', '', text)
            text = re.sub(r'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+' + temp + r'\s*;[ \t]*\n', '', text)
    for rows, symbols, _, _ in used:
        for symbol in symbols:
            declaration = r'(?m)^[ \t]*extern[ \t]+[\w \t]+?[ \t*]' + symbol + r'\s*(?:\[[^\]\n]*\])*\s*;[^\n]*\n'
            head = re.sub(declaration, '', head)
            if re.search(r'\b' + symbol + r'\b', head):
                return []
    out = []
    for signed in (0, 1):
        declared = ''.join(f'extern {_TYPES[size][signed]} {rows}[][{count}];\n' for rows, _, count, size in used)
        out.append((FAMILY, head + declared + '\n' + text + tail))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
