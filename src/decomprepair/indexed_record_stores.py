"""Constant stores through a record's pointer member, `T[i].p`, as the game wrote them: one spelling, in offset order,
each as wide as the target's.

m2c writes a menu or object setup that fills a small structure through `table[i].p` one field at a time, reloading the
index and the pointer at every store. Its draft spells some of the bases `(table + i)->p` or `(*(&table[i])).p`, which
GCC 2.7.2 -O1 keeps an address temporary for (8 bytes of frame nothing reads), writes the first byte as a word, and an
agent's reorderings leave the fields out of offset order. On a KMC 2.7.2 `-O1` setup function those three together
were the last 226 points: the byte alone scored 26, the order alone 206, all three were byte-identical.

indexed_record_stores
    All three at once, then each alone. Only stores of a literal move, and only past each other and past assignments to
    locals nothing reads.
"""
import re

from .csource import _blank, find

FAMILY = 'indexed_record_stores'
FAMILIES = (FAMILY,)
NAME = r'[A-Za-z_]\w*'
_SPELLED = (re.compile(rf'\(\s*({NAME})\s*\+\s*({NAME})\s*\)\s*->\s*({NAME})\b'),
            re.compile(rf'\(\s*\*\s*\(\s*&\s*({NAME})\s*\[\s*({NAME})\s*\]\s*\)\s*\)\s*\.\s*({NAME})\b'))
_BASE = rf'(?P<base>{NAME}\s*\[\s*{NAME}\s*\]\s*\.\s*{NAME})'
_VALUE = r'(?P<value>-?(?:0[xX][0-9a-fA-F]+|\d+))'
_TYPE = r'(?P<type>s8|u8|s16|u16|s32|u32)'
_STORE = re.compile(
    rf'(?m)^[ \t]*(?P<text>\*\s*\(\s*\(\s*{_TYPE}\s*\*\s*\)\s*(?:\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{_BASE}\s*\)\s*\+\s*'
    rf'(?P<offset>0[xX][0-9a-fA-F]+|\d+)\s*\)|(?P<bare>{NAME}\s*\[\s*{NAME}\s*\]\s*\.\s*{NAME}))\s*\)\s*=\s*{_VALUE}\s*;)[ \t]*$')
_ASSIGN = re.compile(rf'\s*(?:({NAME})\s*=(?!=)[^;]*;\s*)*')
_WIDTHS = {'sb': 8, 'sh': 16, 'sw': 32}
_ASM_STORE = re.compile(r'\b(s[bhw])\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$(?!sp\b)\w+\)')


def _spelled(source):
    for pattern in _SPELLED:
        source = pattern.sub(r'\1[\2].\3', source)
    return source


def _offset(store):
    return int(store['offset'] or '0', 0)


def _runs(source, clean, lo, hi):
    """Lists of consecutive store matches through one base, apart only by assignments to locals nothing reads."""
    runs, run = [], []
    for store in _STORE.finditer(clean, lo, hi):
        if run:
            gap = clean[run[-1].end():store.start()]
            names = re.findall(rf'({NAME})\s*=(?!=)', gap)
            unread = all(len(re.findall(rf'\b{n}\b', clean[lo:hi])) <= 2 for n in names)
            same = (store['base'] or store['bare']).split() == (run[-1]['base'] or run[-1]['bare']).split()
            if not (same and _ASSIGN.fullmatch(gap) and unread):
                runs.append(run)
                run = []
        run.append(store)
    runs.append(run)
    return [r for r in runs if len(r) > 1]


def _ordered(source, name):
    span = find(source, name)
    if not span:
        return source
    edits = []
    for run in _runs(source, _blank(source), *span):
        if len({_offset(s) for s in run}) != len(run):
            continue
        for slot, store in zip(run, sorted(run, key=_offset)):
            edits.append((slot.start('text'), slot.end('text'), source[store.start('text'):store.end('text')]))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _widths(source, name, asm):
    """Each store's cast as wide as every target store at its offset, keeping its signedness."""
    span = find(source, name)
    if not span or not asm:
        return source
    seen = {}
    for op, offset in _ASM_STORE.findall(asm):
        seen.setdefault(int(offset, 0), set()).add(_WIDTHS[op])
    edits = []
    for store in _STORE.finditer(_blank(source), *span):
        widths = seen.get(_offset(store), set())
        if len(widths) == 1 and (width := min(widths)) != int(store['type'][1:]):
            edits.append((store.start('type'), store.end('type'), f'{store["type"][0]}{width}'))
    for start, end, text in reversed(edits):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name, asm=''):
    if not find(source, name):
        return []
    spelled = _spelled(source)
    steps = (_widths(_ordered(spelled, name), name, asm), spelled, _ordered(source, name), _widths(source, name, asm))
    result = []
    for child in steps:
        if child != source and child not in [c for _, c in result]:
            result.append((FAMILY, child))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
