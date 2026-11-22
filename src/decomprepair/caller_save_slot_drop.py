"""m2c's caller-saved round trip through a stack local, dropped, and the copy that fed it folded.

GCC 2.x with `-fcaller-saves` (on at -O2) may keep a pseudo that lives across calls in a caller-saved register and save
it to a stack slot around each call (caller-save.c). m2c sees the stores and loads and writes the slot as a local:

    mask = word & 0xFF;
    slot = mask;            /* the first save */
    copy = mask;
    ...
        slot = copy;        /* saved before the call ... */
        copy = slot;        /* ... and read back */
        call(...);

Compiled as written, `slot` is a real local the compiler must keep, and `copy` a second pseudo, so the saved register
lands elsewhere (a KMC gcc 2.7.2 collision sweep had `$s0` where the target keeps the mask in `$t2` and saves it to
0x1a0 itself). The children: every store to the slot and every `x = slot;` right after `slot = x;` dropped; and that
with `copy = mask;` folded too (`copy` replaced by `mask`), so the compiler makes the save itself. On that function
4737 -> 4587 (slot only) -> 4497 (both), the masks then in the target's `$t2`/`$fp` with the target's saves.
That caller-save.c makes the slot is read in the 2.7.2 source; that this was the original's shape is one function.
"""
import re

from .csource import _blank, find

FAMILY = 'caller_save_slot_drop'
COMBINED = 'caller_save_slot_drop_fold'
FAMILIES = (FAMILY, COMBINED)

I = r'[A-Za-z_]\w*'
SCALAR = r'(?:(?:unsigned|signed|register)\s+)*(?:s8|u8|s16|u16|s32|u32|int|short|char|long|unsigned|signed)'


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    return (opening, span[1]) if opening >= 0 else None


def _scalars(text):
    """Plain scalar locals declared alone on a line: name -> the declaration's match."""
    return {m['n']: m for m in re.finditer(r'(?m)^[ \t]*' + SCALAR + r'\s+(?P<n>' + I + r')\s*;[ \t]*\n', text)}


def _drop_slot(body, slot):
    """`body` without the slot: its round trips and stores removed. None when the slot is read any other way."""
    pairs = re.compile(r'(?m)^[ \t]*' + slot + r'\s*=\s*(?P<v>' + I + r')\s*;[ \t]*\n[ \t]*(?P=v)\s*=\s*' + slot +
                       r'\s*;[ \t]*\n')
    text = pairs.sub('', body)
    text = re.sub(r'(?m)^[ \t]*' + slot + r'\s*=\s*' + I + r'\s*;[ \t]*\n', '', text)
    text = re.sub(r'(?m)^[ \t]*' + SCALAR + r'\s+' + slot + r'\s*;[ \t]*\n', '', text, count=1)
    if text == body or re.search(r'\b' + slot + r'\b', _blank(text)):
        return None
    return text


def _fold_copies(body, decls, saved):
    """The first `copy = value;` of a saved variable whose copy has no other assignment, and whose value is a local
    assigned once before it, folded: the copy's uses read the value."""
    clean = _blank(body)
    for copy in decls:
        sets = list(re.finditer(r'(?m)^[ \t]*' + copy + r'\s*=\s*(?P<v>' + I + r')\s*;[ \t]*\n', clean))
        if len(sets) != 1 or sets[0]['v'] not in decls or sets[0]['v'] == copy:
            continue
        value = sets[0]['v']
        if copy not in saved and value not in saved:
            continue
        assigned = r'\b%s\s*(?:[-+*/%%&|^]|<<|>>)?=(?!=)|\+\+\s*%s\b|\b%s\s*\+\+|--\s*%s\b|\b%s\s*--'
        if len(re.findall(assigned % ((copy,) * 5), clean)) != 1:
            continue
        value_sets = [m.start() for m in re.finditer(assigned % ((value,) * 5), clean)]
        if len(value_sets) != 1 or value_sets[0] > sets[0].start():
            continue
        text = body[:sets[0].start()] + body[sets[0].end():]
        text = re.sub(r'(?m)^[ \t]*' + SCALAR + r'\s+' + copy + r'\s*;[ \t]*\n', '', text, count=1)
        text = re.sub(r'\b' + copy + r'\b', value, text)
        return text
    return None


def variants(source, name):
    span = _body(source, name)
    if not span:
        return []
    opening, end = span
    body = source[opening:end]
    decls = _scalars(body)
    result = []
    for slot in decls:
        reads = re.findall(r'\b' + I + r'\s*=\s*' + slot + r'\s*;', _blank(body))
        if not reads:
            continue
        saved = set(re.findall(r'\b' + slot + r'\s*=\s*(' + I + r')\s*;', _blank(body)))
        dropped = _drop_slot(body, slot)
        if dropped is None:
            continue
        result.append((FAMILY, source[:opening] + dropped + source[end:]))
        folded = _fold_copies(dropped, _scalars(dropped), saved)
        if folded is not None:
            result.append((COMBINED, source[:opening] + folded + source[end:]))
    return result[:4]
