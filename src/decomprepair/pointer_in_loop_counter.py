"""A short-lived pointer local carried in the integer a later loop counts with.

A pointer that is set once, read a few times and passed on is a variable with one set, which the scheduler may sink to
its first use and local-alloc places with the block's other short values. Held in a counter the function sets again
later, it is a variable with many sets, allocated by global.c in the register the counter has:

    entry = (u8 *) (offset + (u32) header);        m = (u32) (u8 *) (offset + (u32) header);
    obj->e = *(u16 *) (entry + 0x12);              obj->e = *(u16 *) ((u8 *) m + 0x12);
    ...                                            ...
    for (m = 0; m < 3; m++) ...                    for (m = 0; m < 3; m++) ...

(SN GCC 2.8.1, one N64 model loader: 250 -> exact; scaffolding, evidence is that one function.) Offered for a byte or
void pointer local assigned once, whose every mention comes before the first mention of a 32-bit integer local that is
then set before it is read.
"""
import re

from .case_temporary_repairs import DECLARATION
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'pointer_in_loop_counter'
FAMILIES = (FAMILY,)
LIMIT = 8

_INTS = {'s32', 'u32', 'int', 'unsigned int', 'unsigned'}
_POINTERS = {'u8 *', 's8 *', 'char *', 'unsigned char *', 'void *'}


def variants(source, name, arch=''):
    if arch and not arch.startswith('mips'):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    brace = source.find('{', span[0])
    end = close(clean, brace, '{', '}')
    if end is None or end < 0:
        return []
    declared = {m['name']: (m, ' '.join(m['type'].split())) for m in DECLARATION.finditer(source, brace, end)}

    def mentions(var):
        declaration = declared[var][0]
        return [m for m in re.compile(rf'(?<![\w.])(?<!->){var}\b').finditer(clean, brace, end)
                if not declaration.start() <= m.start() < declaration.end()]

    out = []
    counters = [v for v, (_, kind) in declared.items() if kind in _INTS]
    for pointer, (declaration, kind) in declared.items():
        if kind.replace('*', ' *').replace('  ', ' ') not in _POINTERS:
            continue
        uses = mentions(pointer)
        if len(uses) < 2 or re.search(rf'&\s*{pointer}\b', clean[brace:end]):
            continue
        assign = re.compile(rf'{pointer}[ \t]*=(?!=)[ \t]*(?P<value>[^;{{}}]+);').match(source, uses[0].start())
        writes = re.findall(rf'(?<![\w.>]){pointer}[ \t]*(?:\+\+|--|(?:[-+*/&|^]|<<|>>)?=(?!=))', clean[brace:end])
        if not assign or len(writes) != 1:
            continue
        cast = f"({kind.replace('*', '').strip()} *)"
        for counter in counters:
            later = mentions(counter)
            if not later or later[0].start() < uses[-1].end():
                continue
            if not re.compile(rf'{counter}[ \t]*=(?!=)').match(clean, later[0].start()):
                continue
            edits = [(assign.start(), assign.end(), f"{counter} = (u32) ({assign['value'].strip()});")]
            edits += [(use.start(), use.end(), f'({cast} {counter})') for use in uses[1:]]
            edits.append((declaration.start(), declaration.end(), ''))
            child = source
            for lo, hi, text in sorted(edits, reverse=True):
                child = child[:lo] + text + child[hi:]
            out.append((FAMILY, child))
            if len(out) >= LIMIT:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 1200}
