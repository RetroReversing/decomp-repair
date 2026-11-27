"""`L = L + k;` through a pointer, written as the `L += k;` it came from.

m2c reads a `+=` back as a load, an add and a store that name the place twice, often with a cast around the sum:

    *((int *) ((char *) voice + 0x18)) = (s32) (*((int *) ((char *) voice + 0x18)) + 0x10);

When the place is reached through a `volatile` pointer (a hardware or shared-library record), the two spellings are
different programs to the compiler: the long one loads the pointer twice, the compound one once. An N64 function
(SN GCC 2.8.1, -O2) kept one extra `lw` of the pointer until its store was written `+= 0x10`, and then matched
(110 to 0). `compound_global_update` and `split_read_modify_write` take the forms that go through a temporary; this one
takes the direct form. Every such store is offered together and alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'deref_compound_store'
FAMILIES = (FAMILY,)

_STORE = re.compile(r'(?m)(?<=[;{}\n])(?P<ind>[ \t]*)(?P<lhs>(?:\*|\(|[A-Za-z_])[^;={}\n]*?)\s*=(?!=)\s*(?P<rhs>[^;={}\n]+);')
_CAST = re.compile(r'\(\s*(?:s32|u32|int|long|unsigned|signed|unsigned int|signed int|unsigned long)\s*\)\s*')
_CALL = re.compile(r'(?<![\w.])(?!sizeof\b|M2C_(?:FIELD|BITWISE)\b)[A-Za-z_]\w*\s*\(|\+\+|--')
_TERM = r'(?:-?(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+f?)?)[uUlL]*|[A-Za-z_]\w*(?:(?:->|\.)\w+)*)'
_TAIL = re.compile(r'(?P<op>[-+|&^])(?P<k>.+)\Z', re.S)
LIMIT = 8


def _bare(text):
    """`text` without whole-expression parentheses and 32-bit integer casts in front of it."""
    text = text.strip()
    while True:
        cast = _CAST.match(text)
        if cast:
            text = text[cast.end():].strip()
        elif text.startswith('(') and close(text, 0) == len(text):
            text = text[1:-1].strip()
        else:
            return text


def _squeeze(text):
    return re.sub(r'\s+', '', text)


def _update(lhs, rhs):
    """(operator, operand) when `rhs` is `lhs op operand`, else None."""
    place = _squeeze(_bare(lhs))
    value = _bare(rhs)
    cast = _CAST.match(value)
    if cast:
        value = value[cast.end():]
    # the first operand: a parenthesised group (casts in front of it dropped) or the text of the place itself
    if value.startswith('('):
        end = close(value, 0)
        if end is not None and _squeeze(_bare(value[:end])) == place:
            tail = _TAIL.match(value[end:].strip())
            return _operand(tail)
    squeezed = _squeeze(value)
    if squeezed.startswith(place):
        return _operand(_TAIL.match(squeezed[len(place):]))
    return None


def _operand(tail):
    if not tail:
        return None
    k = tail['k'].strip()
    if re.fullmatch(_TERM, k) or (k.startswith('(') and close(k, 0) == len(k)):
        return tail['op'], k
    return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    edits = []
    for hit in _STORE.finditer(clean, opening, end):
        lhs = source[hit.start('lhs'):hit.end('lhs')].strip()
        rhs = source[hit.start('rhs'):hit.end('rhs')].strip()
        # a place behind a pointer: a plain local or global is the other compound families' business
        if not re.search(r'\*|->|\[', lhs) or _CALL.search(lhs) or _CALL.search(rhs):
            continue
        if re.match(r'(?:const|volatile|static|register|struct|union)\b', lhs):
            continue
        update = _update(lhs, rhs)
        if update:
            edits.append((hit.start('lhs'), hit.end(), f'{lhs} {update[0]}= {update[1]};'))
    if not edits:
        return []

    def apply(chosen):
        text = source
        for start, stop, new in sorted(chosen, reverse=True):
            text = text[:start] + new + text[stop:]
        return text

    result = [apply(edits)] if len(edits) > 1 else []
    result += [apply([edit]) for edit in edits]
    return [(FAMILY, text) for text in dict.fromkeys(result)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 500}
