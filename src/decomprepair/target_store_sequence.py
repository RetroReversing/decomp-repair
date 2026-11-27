"""A run of field stores through one pointer, written in the order the target's store instructions have them.

A near-match that a search has been reordering one swap at a time can hold a run of stores in an order several moves
from the game's, where the single move that scores best is the wrong one. An N64 sound routine (SN GCC 2.8.1, -O2)
wrote its volatile record

    p->0xC = v;  p->0xC = v;  p->0x14 = k;  p->0xC = v;  p->2 = 0;  p->0 = 0x1999;  p->4 = ...

while the target stores 0xC, 0xC, 0xC, 0x14, 0, 2, 4. `store_run_order` and `statement_slide` offer each single move,
and a greedy chain of them stopped at 190 with 0x0 hoisted above 0x14. The target already says the order: this reads
the widths and offsets of its `sb`/`sh`/`sw`/`swc1` instructions and writes the run in that order in one child, which
left the same chain at an exact match (with `branch_value_run_sink` and `deref_compound_store`).

Only consecutive lines that store through the same base text at literal offsets move (`*(T *)((char *)(B) + K)` and
`M2C_FIELD(B, T *, K)`), only when the target has the same stores next to each other, and not when a value calls a
function, steps a variable or reads a field another line of the run writes. Stores to one offset keep their order, and
offsets that partly overlap leave the run alone. That the base register differs between the target's stores is not
checked; the judge decides.
"""
import re
from collections import Counter

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_store_sequence'
FAMILIES = (FAMILY,)
LIMIT = 6

NUMBER = r'0[xX][0-9A-Fa-f]+|\d+'
WIDTHS = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
          'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'long': 4, 'unsigned': 4, 'unsigned int': 4,
          'f32': 4, 'float': 4}
STORED = {'sb': 1, 'sh': 2, 'sw': 4, 'swc1': 4}
TARGET = re.compile(r'\b(sb|sh|sw|swc1)\s+\$\w+\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))?\s*\(\s*\$(\w+)\s*\)')
LINE = re.compile(r'(?m)^[ \t]*(?P<text>[^;{}\n#]+;)[ \t]*(?=\n)')
ASSIGN = re.compile(r'(?<![=!<>])(?:<<|>>|[-+*/%&|^])?=(?!=)')
DEREF = re.compile(r'\*\s*\(\s*(?:volatile\s+)?(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)\s*(?P<stars>\**)\s*\*\s*\)\s*(?=\()')
ADDRESS = re.compile(r'\(\s*(?:char|u8|s8|unsigned char|signed char)\s*\*\s*\)\s*(?P<base>.+?)\s*\+\s*(?P<off>'
                     + NUMBER + r')\Z')
FIELD = re.compile(r'M2C_FIELD\s*\(\s*(?P<base>[^,;]+?)\s*,\s*(?:volatile\s+)?(?P<type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)'
                   r'\s*(?P<stars>\**)\s*\*\s*,\s*(?P<off>' + NUMBER + r')\s*\)\Z')
CAST = re.compile(r'\(\s*(?:(?:const|volatile|unsigned|signed|struct)\s+)*[A-Za-z_]\w*\s*\**\s*\)')
EFFECT = re.compile(r'(?<![\w.>])(?!(?:sizeof|M2C_FIELD)\b)[A-Za-z_]\w*\s*\(|[\])]\s*\(|\+\+|--|(?<![=!<>])=(?!=)')


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _store(text):
    """(base, offset, width, value) of one store line through a base at a literal offset, or None."""
    assigned = ASSIGN.search(text)
    if not assigned:
        return None
    lhs, value = _unwrap(text[:assigned.start()]), text[assigned.end():-1]
    found = FIELD.match(lhs)
    if not found:
        cast = DEREF.match(lhs)
        if not cast or close(lhs, cast.end()) != len(lhs):
            return None
        found = ADDRESS.match(lhs[cast.end() + 1:-1].strip())
        if not found:
            return None
        kind, stars = cast['type'], cast['stars']
    else:
        kind, stars = found['type'], found['stars']
    width = 4 if stars else WIDTHS.get(' '.join(kind.split()))
    if not width:
        return None
    base = re.sub(r'\s+', '', _unwrap(found['base']))
    return base, int(found['off'], 0), width, value


def _movable(run):
    """Whether the lines of a run may change places: no effects, no field of the run read, no partial overlap."""
    offsets = {offset for _, offset, _, _ in run}
    cells = sorted({(offset, width) for _, offset, width, _ in run})
    if any(low + size > high for (low, size), (high, _) in zip(cells, cells[1:])):
        return False
    for base, offset, _, value in run:
        if EFFECT.search(CAST.sub(' ', value)):
            return False
        if base in re.sub(r'[\s()]+', '', value):
            read = {int(number, 0) for number in re.findall(r'\+\s*(' + NUMBER + r')\s*\)', value)}
            if read & (offsets - {offset}):
                return False
    return True


def _runs(source, clean, start, end):
    """Each run of neighbouring store lines through one base: [(line match, parsed store)]."""
    run = []
    for line in LINE.finditer(clean, start, end):
        store = _store(source[line.start('text'):line.end('text')])
        joined = store and run and store[0] == run[-1][1][0] and not clean[run[-1][0].end():line.start()].strip()
        if not joined:
            if len(run) > 1:
                yield run
            run = []
        if store:
            run.append((line, store))
    if len(run) > 1:
        yield run


def _orders(keys, target):
    """The other orders of `keys` the target stores them in next to each other; nothing when it already does."""
    size = len(keys)
    windows = [target[i:i + size] for i in range(len(target) - size + 1)]
    if keys in windows:
        return []
    want = Counter(keys)
    found = []
    for window in windows:
        if Counter(window) == want and window not in found:
            found.append(window)
    return found


def _reordered(source, run, order):
    """The edits that put the run's lines in `order`; lines with one (width, offset) keep their order."""
    queues = {}
    for line, (_, offset, width, _) in run:
        queues.setdefault((width, offset), []).append(source[line.start('text'):line.end('text')])
    return [(line.start('text'), line.end('text'), queues[key].pop(0)) for (line, _), key in zip(run, order)]


def _apply(source, edits):
    for start, stop, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[stop:]
    return source


def variants(source, name, asm):
    span = find(source, name)
    target = [(STORED[op], int(offset or '0', 0)) for op, offset, base in TARGET.findall(asm or '') if base != 'sp']
    if not span or len(target) < 2:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = []
    for run in _runs(source, clean, opening + 1, end - 1):
        keys = [(width, offset) for _, (_, offset, width, _) in run]
        if not _movable([store for _, store in run]):
            continue
        orders = _orders(keys, target)
        if orders:
            sites.append([_reordered(source, run, order) for order in orders[:3]])
    result = []
    if len(sites) > 1:
        result.append(_apply(source, [edit for site in sites for edit in site[0]]))
    for site in sites:
        result += [_apply(source, edits) for edits in site]
    return [(FAMILY, text) for text in dict.fromkeys(result) if text != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 91,
          'archs': ('mips',)}
