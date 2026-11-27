"""The literals that sibling blocks store into fields, named through one local that all of them reuse.

A game that sets up several objects alike writes, in a block per object,

    if (a != 0) { ...; a->state = 2; a->flags = 0x408; ... }
    if (b != 0) { ...; b->state = 3; b->flags = 0x408; ... }

Each literal is a value of its own that lives for two instructions of one block, so gcc 2.7/2.8 local-alloc.c gives it
the first free register before a longer-lived value of the same block (a byte read from the parent and stored last):
the target has them the other way round. One local that every block assigns lives in more than one block, so global.c
allocates it, after local-alloc has given the block's longer-lived value the first register. An N64 object spawner
(SN GCC 2.8.1, `-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float -mfp64`, 134 instructions) went 60 -> 0 with its
two blocks' `state` and `flags` literals written as `held = 2; a->state = held; ... held = 0x408; a->flags = held;`.
Holding only the flags literals was 470 from the same neighbourhood, and the holder needs the blocks' pointers to be
two locals (one shared pointer was 110). The allocation explanation matches `-dl -dg` priorities of the compile
without the holder; that global.c then ranks it above the block's pointer is read from the result, not traced.

sibling_constant_holder
    Sibling blocks are braced bodies (of `if`s) storing non-zero literals to the same offsets or members, through
    whatever pointer. One child per subset of those places (largest first), applied to every block of the group.
"""
import itertools
import re

from .csource import _blank, find
from .goto_structure_repairs import blocks, parse
from .pattern_repairs import close

FAMILY = 'sibling_constant_holder'
FAMILIES = (FAMILY,)
LIMIT = 24
MAX_PLACES = 4

_LITERAL = re.compile(r'-?(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?')
_FIELD = re.compile(r'M2C_FIELD\s*\(\s*(?P<base>[A-Za-z_]\w*)\s*,\s*(?P<type>[^,()]+?)\s*,\s*(?P<at>\w+)\s*\)')
_MEMBER = re.compile(r'(?P<base>[A-Za-z_]\w*)\s*->\s*(?P<at>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)')


def _place(lhs):
    """What the store writes, without which pointer it writes through; None for anything but a field."""
    hit = _FIELD.fullmatch(lhs)
    if hit:
        return ('field', hit['type'].replace(' ', ''), hit['at'])
    hit = _MEMBER.fullmatch(lhs)
    return ('member', hit['at']) if hit else None


def _stores(source, clean, block):
    """{place: (value start, value end, statement start)} for the block's own stores of non-zero literals."""
    found = {}
    for stmt in block:
        if stmt.kind != 'simple':
            continue
        hit = re.fullmatch(r'\s*([^;={}]+?)\s*(?<![-+*/%&|^<>!])=(?!=)\s*([^;={}]+?)\s*;', clean[stmt.start:stmt.end], re.S)
        if not hit:
            continue
        value = source[stmt.start + hit.start(2):stmt.start + hit.end(2)]
        place = _place(source[stmt.start + hit.start(1):stmt.start + hit.end(1)])
        if place and _LITERAL.fullmatch(value) and int(value.rstrip('uU'), 0) and place not in found:
            found[place] = (stmt.start + hit.start(2), stmt.start + hit.end(2), stmt.start)
    return found


def _fresh(clean):
    for number in itertools.count(1):
        name = 'held' if number == 1 else f'held{number}'
        if not re.search(rf'\b{name}\b', clean):
            return name


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    try:
        body = parse(clean, opening + 1, end - 1)
    except ValueError:
        return []
    found = [stores for block in blocks(body) if block is not body for stores in [_stores(source, clean, block)] if stores]
    groups = {}
    for first, second in itertools.combinations(range(len(found)), 2):
        shared = tuple(place for place in found[first] if place in found[second])
        if shared:
            groups.setdefault(shared, set()).update((first, second))
    out = []
    held = _fresh(clean)
    for shared, members in sorted(groups.items(), key=lambda item: -len(item[0])):
        places = shared[:MAX_PLACES]
        for size in range(len(places), 0, -1):
            for chosen in itertools.combinations(places, size):
                edits = []
                for member in sorted(members):
                    for place in chosen:
                        start, stop, statement = found[member][place]
                        line = source.rfind('\n', 0, statement) + 1
                        indent = source[line:statement]
                        gap = '\n' + indent if not indent.strip() else ' '
                        edits.append((statement, statement, f'{held} = {source[start:stop]};{gap}'))
                        edits.append((start, stop, held))
                text = source
                for start, stop, new in sorted(edits, reverse=True):
                    text = text[:start] + new + text[stop:]
                text = text[:opening + 1] + f'\n    s32 {held};' + text[opening + 1:]
                if all(text != seen for _, seen in out):
                    out.append((FAMILY, text))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
