"""A new record's fields copied from another record, written together before the constants stored beside them.

A spawner takes a record from an allocation call and fills it: the position copied from the parent
(`o->x = parent->x; o->y = parent->y;`), then constants (a type word, a state byte). The scheduler delays a copy's
store, often into the next call's delay slot, so m2c writes the second copy after the constants, in the order it met
the stores. The game's source had the two copies together. A 104-instruction N64 spawner (SN GCC 2.8.1
`-G0 -mips3 -O2 -mfp64`) stood at 250 through 22 attempts and 2386 repair trials with two such runs and is exact with
both grouped; one of the two also needed its two constants the other way round. One run alone leaves 190 or 60, and
`store_adjacent_gather` reaches only the run whose pointer is assigned straight from the call (the other takes it
through a second local), so both runs are offered in one child.

A run is consecutive statements storing through one pointer local that only ever holds a call's result, 0 or a copy of
such a local. Each statement is a literal, or a copy of the same cell (offset and width, or member name) of another
pointer that is not such a local; no two cells overlap. In a run with both kinds the copies go first, in the order
written, and the literals follow, as written or reversed. Children (`field_copy_group`): every run grouped, with each
combination of literal orders (fewest reversed first), then each run alone; at most `LIMIT`.

That the allocation call's record is no other pointer's object is an assumption; the judge decides every child.
One match, not read in the compiler source."""
import itertools
import re

from .integer_repair_support import IDENT, view
from .store_run_order import _Bad, _cell, _names, _Parser, _rebuild, _records, _segments

FAMILY = 'field_copy_group'
FAMILIES = (FAMILY,)
LIMIT = 8
RUNS = 4  # runs combined in one child; further runs are only offered alone

_ASSIGNED = re.compile(rf'(?<![\w.>])(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;]*);')
_CALL = re.compile(rf'(?:\([^()]*\)\s*)?{IDENT}\s*\(.*\)', re.S)


def _fresh(body):
    """The names every assignment of which is a call's result, 0 / NULL, or another such name (with at least one of
    the first or last)."""
    values = {}
    for hit in _ASSIGNED.finditer(body):
        values.setdefault(hit['name'], []).append(hit['value'].strip())
    found = set()
    while True:
        more = {name for name, given in values.items() if name not in found
                and all(value in ('0', 'NULL') or value in found or _CALL.fullmatch(value) for value in given)
                and any(value in found or _CALL.fullmatch(value) for value in given)
                and not re.search(rf'(?:\+\+|--)\s*{name}\b|(?<![\w.>]){name}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)', body)}
        if not more:
            return found
        found |= more


def _uncast(node):
    while node[0] == 'cast':
        node = node[2]
    return node


def _kind(source, item, records, fresh):
    """(base, cell, 'copy' | 'literal') of a store this module may move, else None."""
    start, end, effects = item
    if effects.kind != 'store' or effects.store[0] not in fresh:
        return None
    try:
        tree = _Parser(source[start:end].strip().rstrip(';')).parse()
    except _Bad:
        return None
    if tree[0] != 'assign' or tree[1] != '=':
        return None
    base, cell = effects.store[0], effects.store[1:]
    value = _uncast(tree[3])
    if value[0] == 'num' or (value[0] == 'un' and _uncast(value[2])[0] == 'num'):
        return base, cell, 'literal'
    read = _cell(value, records)
    if read and read[0] != base and read[0] not in fresh and read[1:] == cell:
        return base, cell, 'copy'
    return None


def _overlaps(one, other):
    if one[0] != other[0]:
        return True  # two spellings of one record's cells cannot be told apart
    if one[0] == 'off':
        return one[1] < other[2] and other[1] < one[2]
    return one[1] == other[1]


def _runs_of(source, group, records, fresh):
    """[[(index in the group, kind)]]: the maximal stretches of movable stores through one base."""
    found, current, base, cells = [], [], None, []
    for index, item in enumerate(group):
        kind = _kind(source, item, records, fresh)
        if kind and kind[0] == base and not any(_overlaps(kind[1], cell) for cell in cells):
            current.append((index, kind[2]))
            cells.append(kind[1])
            continue
        found.append(current)
        current, base, cells = ([(index, kind[2])], kind[0], [kind[1]]) if kind else ([], None, [])
    found.append(current)
    return [run for run in found if {kind for _, kind in run} == {'copy', 'literal'}]


def _orders(run):
    """The orders offered for one run, as the group indices that fill its places."""
    copies = [index for index, kind in run if kind == 'copy']
    literals = [index for index, kind in run if kind == 'literal']
    orders = [copies + literals]
    if len(literals) > 1:
        orders.append(copies + literals[::-1])
    return orders


def _write(source, groups, chosen):
    """`source` with each (group number, run, order) in `chosen` applied, later groups first."""
    by_group = {}
    for number, run, order in chosen:
        whole = by_group.setdefault(number, list(range(len(groups[number]))))
        for (place, _), index in zip(run, order):
            whole[place] = index
    for number in sorted(by_group, reverse=True):
        source = _rebuild(source, groups[number], by_group[number])
    return source


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__|goto)\b', body):
        return []
    fresh = _fresh(body)
    if not fresh:
        return []
    records = _records(header + '\n' + source)
    groups = _segments(source, part, _names(part, source), records)
    runs = [(number, run) for number, group in enumerate(groups) for run in _runs_of(source, group, records, fresh)]
    together = runs[:RUNS]
    picks = sorted(itertools.product(*(range(len(_orders(run))) for _, run in together)), key=lambda p: (sum(p), p))
    chosen = [[(number, run, _orders(run)[pick]) for (number, run), pick in zip(together, picked)] for picked in picks]
    chosen += [[(number, run, order)] for number, run in runs for order in _orders(run)]
    result = []
    for choice in chosen:
        child = _write(source, groups, choice) if choice else source
        if child != source and child not in result:
            result.append(child)
        if len(result) >= LIMIT:
            break
    return [(FAMILY, child) for child in result]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
