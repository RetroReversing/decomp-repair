"""A guard's load taken before the store that overwrites a field just incremented, so the increment survives.

    o->age++;                       o->age++;
    o->age = 0;              ->     t = o->wait;
    if (o->wait == 0) {             o->age = 0;
                                    if (t == 0) {

Written the first way, GCC deletes the increment (and its load) as a store that is overwritten before anything reads it.
A target that keeps it, `lw v0,0x40; lw v1,0x48; addiu v0,v0,1; sw v0,0x40; bnez v1; sw zero,0x40` (the zero store in
the delay slot), read the guard's field between the two stores: a memory read between them keeps the first. m2c writes
the stores first and the compare after them, so a draft loses the instructions. A 48-instruction N64 spawn routine
(SN GCC 2.8.1, `-G0 -mips3 -O2`) went 1935 -> 1125 on its rewrite and 1709 -> 1219 on its machine draft.

The guard must read another member of the same base as the overwritten one, so the store cannot change its value.
Proposals only; the compiler and the byte judge decide."""
import re

from .integer_repair_support import view
from .pattern_repairs import close

FAMILY = 'guard_load_before_overwrite'
FAMILIES = (FAMILY,)
LIMIT = 6

_CONSTANT = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*|NULL'
_STORE = re.compile(r'(?m)^([ \t]*)([^;{}=\n]+?(?:->|\.)\s*([A-Za-z_]\w*))\s*=\s*(?:' + _CONSTANT + r')\s*;[ \t]*\n(?=[ \t]*if\s*\()')
_GUARD = re.compile(r'\s*(!\s*)?(.+(?:->|\.)\s*([A-Za-z_]\w*))\s*(?:(?:==|!=|<=|>=|<|>)\s*(?:' + _CONSTANT + r')\s*)?', re.S)


def _squash(text):
    return re.sub(r'\s+', '', text)


def _base(access, member):
    return _squash(access)[:-len(member)].rstrip('.').removesuffix('->')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    found = []
    for store in _STORE.finditer(part.clean, part.opening, part.end):
        indent, target, member = store.group(1), store.group(2).strip(), store.group(3)
        earlier = _squash(part.clean[part.opening:store.start()])
        written = re.escape(_squash(target))
        if not re.search(written + r'(?:\+\+|--|[-+]?=(?!=))|(?:\+\+|--)' + written, earlier):
            continue
        paren = part.clean.find('(', store.end())
        stop = close(part.clean, paren)
        if not stop:
            continue
        guard = _GUARD.fullmatch(part.clean[paren + 1:stop - 1])
        if not guard:
            continue
        load, other = guard.group(2).strip(), guard.group(3)
        if other == member or _base(load, other) != _base(target, member) or re.search(r'\+\+|--|&&|\|\||[=,]', load.replace('->', '.')):
            continue
        number = 0
        while re.search(r'\bguard_value%d\b' % number, part.clean):
            number += 1
        local = f'guard_value{number}'
        lo = paren + 1 + guard.start(2)
        hi = lo + len(guard.group(2).rstrip())
        changed = (source[:store.start()] + f'{indent}{local} = (int) {source[lo:hi].strip()};\n'
                   + source[store.start():lo] + local + source[hi:])
        found.append((FAMILY, changed[:part.opening + 1] + f'\n    int {local};' + changed[part.opening + 1:]))
    return found[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
