"""The integer differences a float expression converts, each named in a float local before the statement.

A cross or dot product of points held as integers is drafted as one expression:

    if (((f32) (x1 - x0) * (f32) (y2 - y0)) - ((f32) (y1 - y0) * (f32) (x2 - x0)) < 0.0f)

The original named the edge vectors and multiplied the locals:

    f32 ax, bx, ay, by;
    ax = x1 - x0;
    bx = x2 - x0;
    ay = y1 - y0;
    by = y2 - y0;
    if ((ax * by) - (ay * bx) < 0.0f)

Measured on a 38-instruction N64 triangle winding function (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mgas -mfp32`): the inline
form loaded, subtracted and converted in the expression's own order (1095 from the m2c draft); naming the differences
with the x's together and then the y's was 410, one `terminal_guard_layout` step later 100 and one `staged_store_rise`
step after that exact. The same four locals in the expression's order stayed far off. Why the order matters (the load
order and the conversion's place in the schedule) is read from the output, not from the compiler's source.

For each statement or `if` condition with two or more `(f32) (A - B)` conversions, one child per assignment order: as
written; grouped by what is subtracted (`- x0` together, then `- y0`); grouped and then by the numbers in what is
subtracted from (field offsets or array indices); and by those numbers alone. Only statements that call nothing, assign
at most once and have no `&&`, `||`, `?`, `++` or `--`, so the differences hold the same values when computed first.
A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'float_difference_locals'
FAMILIES = (FAMILY,)
FRESH = 'repair_diff'
SITES = 4
DIFFERENCES = 8

_CAST = re.compile(r'\(\s*(?P<type>f32|float)\s*\)\s*(?=\()')
# `(name)(` is a cast of a parenthesised value, not a call: only a name directly before `(` calls
_CALL = re.compile(rf'(?<![\w.])(?P<name>{IDENT})\s*\(')
_NOT_CALLS = {'if', 'return', 'sizeof', 'M2C_FIELD', 'M2C_BITWISE'}
_STARTS = re.compile(r'(?<=[;{}])\s*')


def _minus(text):
    """Where the last binary `-` outside every bracket is, or None."""
    depth, found = 0, None
    for at, char in enumerate(text):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == '-' and not depth and text[at + 1:at + 2] not in ('>', '-', '=') and text[at - 1:at] != '-':
            if re.search(r'[\w)\]]\s*$', text[:at]):
                found = at
    return found


def _pure(text):
    """Whether nothing in the text calls, steps or branches."""
    if re.search(r'\+\+|--|&&|\|\||\?|<<=|>>=', text):
        return False
    return all(hit['name'] in _NOT_CALLS for hit in _CALL.finditer(text))


def _statements(clean, lo, hi):
    """(start, end) of each expression statement and `if (...)` header that can have lines written above it."""
    for hit in _STARTS.finditer(clean, lo, hi):
        start = hit.end()
        if re.match(r'if\s*\(', clean[start:hi]):
            end = close(clean, clean.index('(', start))
        elif re.match(r'(?:else|for|while|do|switch|case|default|goto|f32|float|struct|union|typedef|extern|static)\b|[{}]',
                      clean[start:hi]) or re.match(rf'(?!return\b){IDENT}[\s*]+{IDENT}\s*[=;,\[]', clean[start:hi]):
            continue
        else:
            end = clean.find(';', start, hi)
            if '{' in clean[start:end]:
                continue
            end = None if end < 0 else end + 1
        if end is not None:
            yield start, end


def _differences(clean, start, end):
    """[(start, stop, minuend, subtrahend)] of the float conversions of a difference in one statement."""
    out = []
    for hit in _CAST.finditer(clean, start, end):
        shut = close(clean, hit.end())
        if shut is None or shut > end:
            continue
        inner = clean[hit.end() + 1:shut - 1]
        at = _minus(inner)
        if at is None:
            continue
        out.append((hit.start(), shut, ' '.join(inner[:at].split()), ' '.join(inner[at + 1:].split())))
    return out


def _numbers(text):
    return [int(word.rstrip('uUlL'), 0) if not re.match(r'0\d', word) else int(word.rstrip('uUlL'))
            for word in re.findall(r'(?<![\w])(?:0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]*(?![\w.])', text)]


def _orders(pairs):
    """The assignment orders of [(minuend, subtrahend)], as lists of indices, the likeliest first."""
    written = list(range(len(pairs)))
    first = {}
    for index, (_, subtrahend) in enumerate(pairs):
        first.setdefault(subtrahend, index)
    grouped = sorted(written, key=lambda i: first[pairs[i][1]])
    numbered = sorted(written, key=lambda i: (first[pairs[i][1]], _numbers(pairs[i][0])))
    alone = sorted(written, key=lambda i: _numbers(pairs[i][0]))
    out = []
    for order in (numbered, grouped, written, alone):
        if order not in out:
            out.append(order)
    return out


def variants(source, name):
    part = view(source, name)
    if not part or FRESH in source or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    clean, out, sites = part.clean, [], 0
    for start, end in _statements(clean, part.opening, part.end - 1):
        found = _differences(clean, start, end)
        text = clean[start:end]
        if (len(found) < 2 or sites == SITES or not _pure(text)
                or len(re.findall(r'(?<![=!<>])=(?!=)', text)) > (0 if text.startswith('if') else 1)):
            continue
        # one local for each distinct difference, however often the statement converts it
        pairs = list(dict.fromkeys((minuend, subtrahend) for _, _, minuend, subtrahend in found))
        if not 2 <= len(pairs) <= DIFFERENCES:
            continue
        sites += 1
        line = clean.rfind('\n', 0, start) + 1
        indent = clean[line:start] if not clean[line:start].strip() else '    '
        kind = _CAST.match(clean, found[0][0])['type']
        for order in _orders(pairs):
            names = {pairs[index]: f'{FRESH}{position}' for position, index in enumerate(order)}
            values = {}
            for cast, stop, minuend, subtrahend in found:
                inner = _CAST.match(clean, cast).end()
                values.setdefault((minuend, subtrahend), source[inner + 1:stop - 1].strip())
            declared = ''.join(f'\n    {kind} {FRESH}{position};' for position in range(len(order)))
            assigned = ''.join(f'{names[pairs[index]]} = {values[pairs[index]]};\n{indent}' for index in order)
            edits = [(part.opening + 1, part.opening + 1, declared), (start, start, assigned)]
            edits += [(cast, stop, names[minuend, subtrahend]) for cast, stop, minuend, subtrahend in found]
            out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
