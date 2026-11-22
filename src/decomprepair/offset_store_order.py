"""A run of stores to one record, written in an order the target does not have, put in order of their offsets.

m2c writes a record's fields in the order its own expressions need them (the zero words first, then the products it
found, the last field it computed last), and an agent editing its output keeps that order. The hand-written original
stored the fields in order of their offsets. GCC 2.7.2's first scheduler breaks ties by the order of the original insns
and the second by the order the first one left, so the order the stores are written in decides which of the many
equal-priority products is computed first and so which registers they get. A 4x4 rotation-matrix builder (KMC GCC
2.7.2, sixteen word stores through one pointer) stood at 160 in m2c's order and at 35 with the same stores in order of
their offsets, with no other change; its remaining rows were three registers.

This module reads the statement forms m2c and the agents write for such a record, which `store_expression_form` (an
`array[N]` run) and `store_run_move` (one move, field names) do not:

    (*(f32 *)((char *)(arg0) + 0x2C)) = value;                     a byte-offset store, the cast spelled out
    *(int *)((char *)arg0 + 4) = bits;                              the same without the outer parentheses
    { union { f32 f; int i; } v; v.f = value; *(int *)((char *)arg0 + 4) = v.i; }     a float's bits stored as a word
    arg0[3] = value;                                                a constant index

and a local assigned from locals (`product = a * b;`), which a store may read. A run is the statements between two
barriers (a call, a branch, a label, a declaration, a store through another pointer, any expression that reads memory);
the offsets of its stores must be distinct and not overlap (a store's size is its cast's type). No statement moves past
one it depends on: a store keeps the locals it reads before it, a local keeps the stores that read its old value before
it.

Children (each only when it differs from the source), bounded by the run:
- the stores in ascending order of offset, the locals no store reads first and each other local just before the first
  store that needs it (`offset_store_order`);
- the same with every local hoisted to the top of the run in its own order (`offset_store_order_hoisted`);
- the stores in descending order (`offset_store_order_descending`), for a target that writes a record from its end.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'offset_store_order'
FAMILY_HOISTED = 'offset_store_order_hoisted'
FAMILY_DESCENDING = 'offset_store_order_descending'
FAMILIES = (FAMILY, FAMILY_HOISTED, FAMILY_DESCENDING)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
SIZES = {'f32': 4, 'float': 4, 's32': 4, 'u32': 4, 'int': 4, 'unsigned': 4, 'long': 4, 'f64': 8, 'double': 8,
         's64': 8, 'u64': 8, 's16': 2, 'u16': 2, 'short': 2, 's8': 1, 'u8': 1, 'char': 1}
TYPE = r'(?:(?:unsigned|signed|const|volatile)\s+)*(?:' + '|'.join(sorted(SIZES, key=len, reverse=True)) + r')'
BASE = rf'\(?\s*({IDENT})\s*\)?'
OFFSET_STORE = re.compile(
    rf'\(?\s*\*\s*\(\s*({TYPE})\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*{BASE}\s*(?:\+\s*({NUMBER})\s*)?\)\s*\)?\s*=(?!=)\s*(.+?)\s*;\Z', re.S)
INDEX_STORE = re.compile(rf'({IDENT})\s*\[\s*({NUMBER})\s*\]\s*=(?!=)\s*(.+?)\s*;\Z', re.S)
LOCAL = re.compile(rf'({IDENT})\s*(\+|-|\*|/)?=(?!=)\s*(.+?)\s*;\Z', re.S)
UNION = re.compile(
    rf'\{{\s*union\s*\{{\s*({TYPE})\s+({IDENT})\s*;\s*({TYPE})\s+({IDENT})\s*;\s*\}}\s*({IDENT})\s*;\s*'
    rf'\5\s*\.\s*(\2|\4)\s*=(?!=)\s*(.+?)\s*;\s*'
    rf'\*\s*\(\s*({TYPE})\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*{BASE}\s*(?:\+\s*({NUMBER})\s*)?\)\s*=(?!=)\s*\5\s*\.\s*(\2|\4)\s*;\s*\}}', re.S)
KEYWORD = re.compile(r'(?:if|else|for|while|do|switch|case|default|return|goto|break|continue|typedef|struct|union|enum|'
                     r'static|extern|volatile|register|unsigned|signed|const|void|char|short|int|long|float|double|'
                     r'f32|f64|[su](?:8|16|32|64))\b')
CALL = re.compile(r'\w\s*\(')
MEMORY = re.compile(r'\[|->|(?<=[\w)\]])\.(?=[A-Za-z_])|&|(?:^|[(=+\-*/,<>!&|^?:])\s*\*')
LIMIT = 24


class Unit:
    """One statement of a run: where it is, what it reads and what it writes."""

    def __init__(self, begin, stop, reads, local=None, base=None, offset=None, size=None):
        self.begin, self.stop = begin, stop
        self.reads, self.local = reads, local
        self.base, self.offset, self.size = base, offset, size

    @property
    def is_store(self):
        return self.base is not None


def _pure(text):
    """No call and no memory read: the value depends on the names alone (a cast of a name is fine)."""
    return not CALL.search(re.sub(rf'\(\s*{TYPE}\s*\)', ' ', text)) and not MEMORY.search(text) and '++' not in text and '--' not in text


def _names(text):
    return set(re.findall(rf'(?<![\w.>]){IDENT}\b', re.sub(rf'\(\s*{TYPE}\s*\)', ' ', text))) - set(SIZES)


def _number(text):
    return int(text, 0) if text else 0


def _unit(source, clean, pos):
    """(Unit or None, next position). None marks a barrier."""
    if clean[pos] == '{':
        match = UNION.match(source, pos)
        if match:
            first, f1, second, f2, var, written, value, kind, base, offset, read = match.groups()
            if written != read and _pure(value):
                return Unit(pos, match.end(), _names(value) | {base}, base=base, offset=_number(offset),
                            size=SIZES.get(kind.split()[-1], 4)), match.end()
        return None, pos + 1
    if clean[pos] == '}':
        return None, pos + 1
    stop = clean.find(';', pos)
    brace = re.search(r'[{}]', clean[pos:stop + 1]) if stop >= 0 else None
    if stop < 0 or brace:
        return None, pos + (brace.start() if brace and brace.start() else 1)
    text = clean[pos:stop + 1]
    if KEYWORD.match(text):
        return None, stop + 1
    match = OFFSET_STORE.match(text)
    if match:
        kind, base, offset, value = match.groups()
        if _pure(value):
            return Unit(pos, stop + 1, _names(value) | {base}, base=base, offset=_number(offset),
                        size=SIZES.get(kind.split()[-1], 4)), stop + 1
        return None, stop + 1
    match = INDEX_STORE.match(text)
    if match:
        base, index, value = match.groups()
        if _pure(value):
            return Unit(pos, stop + 1, _names(value) | {base}, base=base, offset=_number(index), size=1), stop + 1
        return None, stop + 1
    match = LOCAL.match(text)
    if match and not text.lstrip().startswith(('*', '(')) and _pure(match[3]):
        name, operator, value = match.groups()
        return Unit(pos, stop + 1, _names(value) | ({name} if operator else set()), local=name), stop + 1
    return None, stop + 1


def _runs(source, clean, start, end):
    runs, run, pos = [], [], start
    while pos < end:
        if clean[pos].isspace():
            pos += 1
            continue
        unit, nxt = _unit(source, clean, pos)
        if unit is None:
            runs.append(run)
            run = []
        else:
            run.append(unit)
        pos = max(nxt, pos + 1)
    runs.append(run)
    return runs


def _conflict(a, b):
    """May `a` (earlier) not move past `b`?"""
    if a.is_store and b.is_store:
        return a.base == b.base and a.offset < b.offset + b.size and b.offset < a.offset + a.size
    if a.local and b.local and a.local == b.local:
        return True
    if a.local and a.local in b.reads or b.local and b.local in a.reads:
        return True
    return False


def _order(units, mode):
    """The units as indices in the new order: the stores by offset, each with the locals it needs before it."""
    count = len(units)
    before = [[i for i in range(j) if _conflict(units[i], units[j])] for j in range(count)]
    stores = [i for i in range(count) if units[i].is_store]
    key = (lambda i: -units[i].offset) if mode == 'descending' else (lambda i: units[i].offset)
    placed, order = set(), []

    def emit(i):
        for p in before[i]:
            if p not in placed:
                emit(p)
        if i not in placed:
            placed.add(i)
            order.append(i)

    if mode == 'hoisted':
        for i in range(count):
            if not units[i].is_store:
                emit(i)
    else:
        needed = set()
        for s in stores:
            needed |= _closure(before, s)
        for i in range(count):
            if not units[i].is_store and i not in needed:
                emit(i)
    for s in sorted(stores, key=key):
        emit(s)
    for i in range(count):
        emit(i)
    return order


def _closure(before, i):
    seen, todo = set(), list(before[i])
    while todo:
        p = todo.pop()
        if p not in seen:
            seen.add(p)
            todo.extend(before[p])
    return seen


def _text(source, units, order, indent):
    first, last = units[0].begin, units[-1].stop
    gaps = [source[units[i].stop:units[i + 1].begin] for i in range(len(units) - 1)]
    body = source[units[order[0]].begin:units[order[0]].stop]
    for k in range(1, len(order)):
        body += (gaps[k - 1] if '\n' in gaps[k - 1] else '\n' + indent) + source[units[order[k]].begin:units[order[k]].stop]
    return source[:first] + body + source[last:]


def _eligible(units):
    """The run's stores share one base, have distinct non-overlapping offsets, and there are enough of them."""
    stores = [u for u in units if u.is_store]
    if len(stores) < 3 or len({u.base for u in stores}) != 1 or len(stores) > LIMIT:
        return False
    ranges = sorted((u.offset, u.offset + u.size) for u in stores)
    return all(ranges[i][1] <= ranges[i + 1][0] for i in range(len(ranges) - 1))


def variants(source, name):
    part = find(source, name)
    if not part:
        return []
    clean = _blank(source)
    definition = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[part[0]:part[1]])
    if not definition or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp|switch|volatile)\b|^\s*#', clean[part[0]:part[1]], re.M):
        return []
    opening = part[0] + definition.end() - 1
    end = close(clean, opening, '{', '}') or part[1]
    result = []
    for units in _runs(source, clean, opening + 1, end - 1):
        if not _eligible(units):
            continue
        # a store keeps the stores the run holds between it and a barrier: the run is the statements it spans
        line = source.rfind('\n', 0, units[0].begin) + 1
        indent = re.match(r'[ \t]*', source[line:units[0].begin])[0]
        for mode, family in (('lazy', FAMILY), ('hoisted', FAMILY_HOISTED), ('descending', FAMILY_DESCENDING)):
            order = _order(units, mode)
            if order == list(range(len(units))):
                continue
            text = _text(source, units, order, indent)
            if text != source and text not in [t for _, t in result]:
                result.append((family, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
