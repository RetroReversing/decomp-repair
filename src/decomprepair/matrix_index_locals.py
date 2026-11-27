"""The two loaded indexes of a table read, held in `s32` locals on the lines before it.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O1`) leaf that looks one byte up in a two-dimensional table by
two fields of a record, `n = T[rec[i].d][rec[i].c];`. In one expression gcc loads the row first and adds the column last,
from a register it fills between the two. The target loads the column first, then the row, then the table's address: the
game wrote `col = rec[i].c; row = rec[i].d; n = T[row][col];` with `s32` locals (675 -> 0; the same locals `s8` stayed
at 675, row loaded first scored 50). The same read as m2c writes it, `*(((row * K) + T) + col)`, is staged too.

matrix_index_locals
    In one plain assignment without calls, a read whose two indexes both load memory gets them staged in two new `s32`
    locals, column first and row first (two children per read).

Hypothesis from the match, not from the compiler source: the locals order the two loads. The exact judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'matrix_index_locals'
FAMILIES = (FAMILY,)
LIMIT = 8
ROW, COL = '__repair_row', '__repair_col'
# a plain assignment alone on its line: no call or condition before the `=`
_STATEMENT = re.compile(r'(?m)^[ \t]*(?P<text>[^\s;{}][^;{}=\n()]*=(?!=)[^;{}]*;)')
_CALL = re.compile(r'(?<![\w)\]])\b(?!sizeof\b)[A-Za-z_]\w*\s*\(|[\]\)]\s*\(\s*[\w*&]*\s*\)\s*\(')
_EFFECT = re.compile(r'\+\+|--|\?|&&|\|\||(?<![=!<>])=(?!=)')
_SUBSCRIPT = re.compile(r'(?<![\w.>\]])[A-Za-z_]\w*\s*(?=\[)')
_LOAD = re.compile(r'\[|->|(?<![\w\s.])\.(?=[A-Za-z_])|(?<=[\w\]\)])\.(?=[A-Za-z_])|(?:^|[(+\-,])\s*\*')
_STAR = re.compile(r'(?<![\w\)\]])\*\s*(?=\()')


def _trim(text, first, last):
    while first < last and text[first].isspace():
        first += 1
    while last > first and text[last - 1].isspace():
        last -= 1
    return first, last


def _unwrapped(text, first, last):
    """The span without the parentheses around the whole of it."""
    first, last = _trim(text, first, last)
    while first < last and text[first] == '(' and close(text, first, '(', ')') == last:
        first, last = _trim(text, first + 1, last - 1)
    return first, last


def _terms(text, first, last, operator):
    """The spans of `text[first:last]` split at its top-level `operator`s."""
    depth, start, spans = 0, first, []
    for at in range(first, last):
        char = text[at]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == operator and not depth and at > start and text[start:at].strip():
            if operator == '*' and not re.search(r'[\w\)\]]\s*$', text[start:at]):
                continue
            spans.append((start, at))
            start = at + 1
    spans.append((start, last))
    return spans


def _subscripts(text):
    """(row span, column span) of every `a[row][column]`."""
    for base in _SUBSCRIPT.finditer(text):
        spans, at = [], base.end()
        while at < len(text) and text[at] == '[':
            end = close(text, at, '[', ']')
            if not end:
                break
            spans.append((at + 1, end - 1))
            at = end
            while at < len(text) and text[at] in ' \t':
                at += 1
        if len(spans) == 2:
            yield spans[0], spans[1]


def _pointers(text):
    """(row span, column span) of every `*(((row * K) + table) + column)`."""
    for star in _STAR.finditer(text):
        opening = star.end()
        end = close(text, opening, '(', ')')
        if not end:
            continue
        outer = _terms(text, *_unwrapped(text, opening, end), '+')
        if len(outer) != 2:
            continue
        for address, column in (outer, outer[::-1]):
            inner = _terms(text, *_unwrapped(text, *address), '+')
            if len(inner) != 2:
                continue
            for scaled in inner:
                factors = _terms(text, *_unwrapped(text, *scaled), '*')
                if len(factors) == 2 and re.fullmatch(r'\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*', text[slice(*factors[1])]):
                    yield _unwrapped(text, *factors[0]), _unwrapped(text, *column)


def variants(source, name, header=''):
    part = view(source, name)
    if not part or ROW in source or COL in source:
        return []
    clean, low, high = part.clean, part.opening + 1, part.end
    children = []
    for statement in _STATEMENT.finditer(clean, low, high):
        start, stop = statement.span('text')
        # a statement standing alone as the body of a braceless `if` or loop cannot be split
        if not clean[:start].rstrip().endswith((';', '{', '}')):
            continue
        text = clean[start:stop]
        left = text.index('=') + 1
        if _CALL.search(text) or _EFFECT.search(text, left):
            continue
        indent = source[source.rfind('\n', 0, start) + 1:start]
        for row, column in [*_subscripts(text), *_pointers(text)]:
            if row[0] < left or not (_LOAD.search(text[slice(*row)]) and _LOAD.search(text[slice(*column)])):
                continue
            loads = {name_: source[start + span[0]:start + span[1]].strip()
                     for name_, span in ((ROW, row), (COL, column))}
            for order in ((COL, ROW), (ROW, COL)):
                lines = ''.join(f'{local} = {loads[local]};\n{indent}' for local in order)
                changes = [(start, start, lines), (start + row[0], start + row[1], ROW),
                           (start + column[0], start + column[1], COL),
                           (low, low, f'\n  s32 {ROW};\n  s32 {COL};')]
                children.append((FAMILY, edit(source, changes)))
    return children[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
