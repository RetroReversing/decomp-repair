"""A byte table the target loads a pointer from, read through that pointer in the C too.

m2c and agents write a table of records whose first word is a pointer as plain bytes, with the pointed-to field's offset
added to the table's address: `*(s16 *)(D_TABLE + index * 100 + 0xA)`. The target loads the word first and stores
through it (`lw $a0, %lo(D_TABLE)($a0); sh $v1, 0xA($a0)`), once per store since a store through a pointer may change
the table. The original is `*(s16 *)(*(u8 **)(D_TABLE + index * 100) + 0xA)`. A 128-instruction record state handler
(KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`) went from its first draft's 2805 to 300, and `product_temporary` took
it to 0.

Read off the target: a symbol is offered when a `lw` of `%lo(SYM)` is followed by an access at `K($reg)` through the
loaded register before it is written again, and the C accesses `SYM + ... + K` for such a `K`. `SYM` must be declared
a byte array (otherwise the arithmetic is scaled). A candidate for the exact judge, never a verdict.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'pointer_table_deref'
FAMILIES = (FAMILY,)
LIMIT = 8
_LOAD = re.compile(r'\blw\s+\$(\w+)\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)')
_ACCESS = re.compile(r'\b(?:lbu|lb|lhu|lh|lw|lwc1|ldc1|sb|sh|sw|swc1|sdc1)\s+\$\w+\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\(\$(\w+)\)')
_WRITES = re.compile(r'^\s*(?!(?:sb|sh|sw|swc1|sdc1|b\w*|j|jr)\b)[a-z][\w.]*\s+\$(\w+)\b')
_CAST = re.compile(r'\*\s*(?=\(\s*\(?\s*(?:(?:unsigned|signed|struct)\s+)?[A-Za-z_]\w*\s*\*)')
_NUMBER = re.compile(r'\s*(0[xX][0-9a-fA-F]+|\d+)\s*$')


def _offsets(asm):
    """{symbol: {offsets the target accesses through a word loaded from it}}."""
    holds, found = {}, {}
    for line in (asm or '').splitlines():
        line = re.sub(r'/\*.*?\*/', ' ', line).strip()
        access = _ACCESS.search(line)
        if access and access[2] in holds:
            found.setdefault(holds[access[2]], set()).add(int(access[1], 0))
        written = _WRITES.match(line)
        if written:
            holds.pop(written[1], None)
        load = _LOAD.search(line)
        if load:
            holds[load[1]] = load[2]
        if line.startswith('jal'):
            holds.clear()
    return found


def _terms(text):
    """The `+` terms of `text`, with parentheses around a whole sum opened."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') in (len(text) - 1, len(text)):
        text = text[1:-1].strip()
    parts, depth, last = [], 0, 0
    for pos, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == '+' and not depth and text[pos - 1:pos] != '+' and text[pos + 1:pos + 2] not in ('+', '='):
            parts.append(text[last:pos].strip())
            last = pos + 1
    parts.append(text[last:].strip())
    if len(parts) > 1 and parts[0].startswith('('):
        parts = _terms(parts[0]) + parts[1:]
    return parts


def _end(clean, opening):
    stop = close(clean, opening, '(', ')')
    if stop is None:
        return None
    return stop if clean[stop - 1] == ')' else stop + 1


def _edits(source, clean, span, symbol, offsets):
    edits = []
    for hit in _CAST.finditer(clean, span[0], span[1]):
        opening = clean.index('(', hit.end() - 1)
        stop = _end(clean, opening)
        if stop is None:
            continue
        # `*((T *) (...))` or `*(T *)(...)`
        inner = clean[opening + 1:stop - 1].strip()
        if inner.startswith('('):
            cast_at = clean.index('(', opening + 1)
            cast_stop = _end(clean, cast_at)
            outer_stop = stop
        else:
            cast_at, cast_stop, outer_stop = opening, stop, None
        if cast_stop is None or not clean[cast_at + 1:cast_stop - 1].rstrip().endswith('*'):
            continue
        rest = re.compile(r'\s*\(').match(clean, cast_stop)
        if not rest:
            continue
        start = rest.end() - 1
        end = _end(clean, start)
        if end is None or (outer_stop is not None and end > outer_stop):
            continue
        terms = _terms(source[start + 1:end - 1])
        if len(terms) < 2 or terms[0] != symbol:
            continue
        number = _NUMBER.match(terms[-1])
        if not number or int(number[1], 0) not in offsets:
            continue
        base = ' + '.join(terms[:-1])
        edits.append((start, end, f'(*(u8 **)({base}) + {number[1]})' if len(terms) > 2
                      else f'(*(u8 **){base} + {number[1]})'))
    return edits


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name, asm='', header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    declared = _blank(header) + '\n' + clean
    per = []
    for symbol, offsets in sorted(_offsets(asm).items()):
        if not re.search(rf'\b(?:u8|s8|char)\s+{re.escape(symbol)}\s*\[', declared):
            continue
        edits = _edits(source, clean, span, symbol, offsets)
        if edits:
            per.append(edits)
    out = []
    if len(per) > 1:
        out.append(_apply(source, [edit for edits in per for edit in edits]))
    out += [_apply(source, edits) for edits in per]
    return [(FAMILY, child) for child in out[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'archs': ('mips',), 'order': 60}
