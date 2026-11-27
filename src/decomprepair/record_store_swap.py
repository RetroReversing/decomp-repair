"""Two adjacent stores into one record swapped, when the value of one is read through another pointer.

The game wrote `child->kind = owner->kind; child->owner = owner;` where m2c emitted the two the other way round, and
the first scheduler keeps the source's order for stores it cannot separate (a 131-instruction spawn-point routine, SN
GCC 2.8.1: 60 -> 0 as the last step). `statement_slide` does not move them: the read is through `owner` and the store
through `child`, which it takes as possibly the same memory. Here the two stores are to disjoint bytes of one pointer
and neither value reads a byte either one writes *through that pointer*; that a different pointer overlaps the record
is a guess the judge checks.

record_store_swap
    Each adjacent pair `M2C_FIELD(a, T *, o) = x; M2C_FIELD(a, U *, p) = y;` with disjoint byte intervals, no calls,
    no `++`/`--`, and no read of `a`'s own written bytes, swapped; at most `LIMIT` children.
"""
import re

from .csource import _blank, find

FAMILY = 'record_store_swap'
FAMILIES = (FAMILY,)
LIMIT = 24

WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4}
FIELD = r'M2C_FIELD\(\s*(?P<base>[A-Za-z_]\w*)\s*,\s*(?P<type>[\w ]+?\**)\s*\*\s*,\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)'
STORE = re.compile(r'(?m)^[ \t]*' + FIELD + r'[ \t]*=(?!=)[ \t]*(?P<value>[^;{}]*);[ \t]*$')
READ = re.compile(FIELD)
CALL = re.compile(r'\b(?!(?:s8|u8|s16|u16|s32|u32|f32|int|char|short|long|unsigned|signed|M2C_FIELD)\b)[A-Za-z_]\w*\s*\(')


def _interval(type_name, off):
    width = 4 if type_name.strip().endswith('*') else WIDTH.get(type_name.strip())
    if width is None:
        return None
    at = int(off, 0)
    return at, at + width


def _independent(one, other):
    """The store `one` does not read, through its own base, what `other` writes."""
    written = _interval(other['type'], other['off'])
    for read in READ.finditer(one['value']):
        span = _interval(read['type'], read['off'])
        if read['base'] == other['base'] and (span is None or span[0] < written[1] and written[0] < span[1]):
            return False
    return True


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    stores = list(STORE.finditer(clean, span[0], span[1]))
    result = []
    for first, second in zip(stores, stores[1:]):
        if len(result) >= LIMIT:
            break
        if clean[first.end():second.start()].strip() or first['base'] != second['base']:
            continue
        a, b = _interval(first['type'], first['off']), _interval(second['type'], second['off'])
        if a is None or b is None or (a[0] < b[1] and b[0] < a[1]):
            continue
        values = (first['value'], second['value'])
        if any(CALL.search(v) or '++' in v or '--' in v or re.search(r'(?<![=!<>])=(?!=)', v) for v in values):
            continue
        if not (_independent(first, second) and _independent(second, first)):
            continue
        if not any(read['base'] != first['base'] for v in values for read in READ.finditer(v)):
            continue  # nothing read through another pointer: statement_slide already moves it
        text = (source[:first.start()] + source[second.start():second.end()] + source[first.end():second.start()]
                + source[first.start():first.end()] + source[second.end():])
        result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
