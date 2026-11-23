"""A signed halfword table value added into a narrower store, read through a full-width local first.

`*(u16 *)(p + 0x1BC) += tbl[i * 2];` with `tbl` a table of `s16` compiles to `lhu` for the table read: the store keeps
only the low halfword of the sum, so combine drops the sign extension from the load. The game's table read was the sign
extending `lh`: its source had the value in a local of its own, and a local of a full-width type (`s32 delta; delta =
tbl[i * 2]; *(u16 *)(p + 0x1BC) += delta;`) keeps the extension, because the sum is then of two words. (An `s16` local
does not: the pseudo is a halfword and combine folds it the same way.) One local per site; the local is declared with the
function's others.

Offered for each such statement, and for all of them together. `assign_after_use_swap` (an uninitialised pointer local
whose assignment follows the compound assignment) reuses `widen` for the combination its function needed: the swap
alone changes nothing the judge sees until the table read is wide, and the wide local alone reads the same register.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'narrow_table_addend'
FAMILIES = (FAMILY,)

LIMIT = 6
IDENT = r'[A-Za-z_]\w*'
_SIGNED = r'(?:s8|s16|short|signed\s+short|signed\s+char)'
_STATEMENT = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<lhs>\(?\s*\*\s*\(\s*(?:u8|s8|u16|s16|unsigned\s+short|short|unsigned\s+char)\s*\*\s*\)(?:[^;{}\n=]|=(?!=))*?\)?)'
    r'[ \t]*(?P<op>[-+|&^])=[ \t]*(?P<rhs>(?P<table>' + IDENT + r')\s*\[[^;{}\n]*\])[ \t]*;[ \t]*\n')


def _signed_tables(clean, opening, end, header):
    context = _blank(header) + '\n' + clean[:opening] + clean[end:]
    return set(re.findall(r'(?m)^[ \t]*(?:extern\s+)?' + _SIGNED + r'\s+(' + IDENT + r')\s*\[', context))


def widen(source, name, header='', only=None):
    """Every qualifying statement rewritten with a wide local (or only the `only`th); None when nothing qualifies."""
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or re.search(r'\b(?:volatile|asm)\b', clean[opening:end]):
        return None
    tables = _signed_tables(clean, opening, end, header)
    hits = [m for m in _STATEMENT.finditer(clean, opening + 1, end) if m['table'] in tables
            and not re.search(r'\+\+|--|' + IDENT + r'\s*\(', source[m.start('rhs'):m.end('rhs')])]
    if only is not None:
        hits = hits[only:only + 1]
    if not hits:
        return None
    text, declarations = source, ''
    for number, hit in reversed(list(enumerate(hits, 1))):
        wide = f'__repair_wide{number}'
        declarations = f'    s32 {wide};\n' + declarations
        indent = hit['indent']
        lhs = source[hit.start('lhs'):hit.end('lhs')]
        rhs = source[hit.start('rhs'):hit.end('rhs')]
        new = f'{indent}{wide} = {rhs};\n{indent}{lhs} {hit["op"]}= {wide};\n'
        text = text[:hit.start()] + new + text[hit.end():]
    head = text.index('{', span[0]) + 1
    return text[:head] + '\n' + declarations.rstrip('\n') + text[head:]


def variants(source, name, header=''):
    result = []
    everything = widen(source, name, header)
    if everything is None:
        return []
    count = everything.count('__repair_wide') // 2 - 0
    if count > 1:
        result.append((FAMILY, everything))
    for index in range(min(count, LIMIT)):
        one = widen(source, name, header, index)
        if one and one != source and (FAMILY, one) not in result:
            result.append((FAMILY, one))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
