"""A constant store written below the call it was put above, and two neighbouring field stores moved together.

A 107-instruction N64 particle spawner (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`) fills a new record with a run of
field stores between and after two calls. Its saved C had a constant store above the statement holding the second call
(an earlier rewrite had moved it there, and the score improved), and two stores later in the run the wrong side of two
others. The target stores the constant after that call (it sits in a multiply's latency), so the C that matched writes
it in the middle of the later run: 390 -> 0, only with both moves at once. No move of one statement (adjacent swap,
front, back, one or two places across a call) got there: each half alone scored no better than the source.

`sunk_store_pair_order`: a literal store to a field that has a call statement below it in the same run of statements,
moved to each later place; alone, and together with each move of two adjacent field stores. `store_pair_move`: two
adjacent field stores moved together to another place among their neighbouring field stores.

A field is told apart by its member name or its byte offset, whatever the base pointer, so two accesses to one name or
offset never pass each other. A constant store passes only statements that don't name its field, and no call that takes
its base as an argument. That a callee reaches the record some other way is not ruled out: these are hypotheses about
the order the game wrote, and the judge decides each one. That the scheduler's tie-break between independent stores is
what makes the order matter is a hypothesis too (not confirmed in the compiler source).

Children: [(family, source)], the combined ones first, bounded to `LIMIT`."""
import re

from .integer_repair_support import IDENT, NUMBER, view
from .statement_slide import _runs

FAMILY = 'sunk_store_pair_order'
FAMILY_PAIR = 'store_pair_move'
FAMILIES = (FAMILY, FAMILY_PAIR)
LIMIT = 160
PAIR_LIMIT = 40
_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'do', 'else'}
_TYPE_END = re.compile(r'(?:\b(?:char|short|int|long|float|double|void|unsigned|signed|[suf](?:8|16|32|64))|\*)\s*$')
_OFFSET = re.compile(rf'\(\s*(?:char|u8|s8)\s*\*\s*\)\s*\(?\s*({IDENT})\s*\)?\s*\+\s*({NUMBER})')
_M2C = re.compile(rf'M2C_FIELD\(\s*({IDENT})\s*,[^,()]+,\s*({NUMBER})\s*\)')
_MEMBER = re.compile(rf'\b({IDENT})\s*(?:->|\.)\s*({IDENT})')
_ASSIGNS = re.compile(r'(?<![=!<>+\-*/&|^%])=(?!=)')


def _calls(text):
    """The argument text of every call in a statement (casts and keywords aside)."""
    found = []
    for hit in re.finditer(rf'\b({IDENT})\s*\(', text):
        name = hit[1]
        if name in _KEYWORDS or name == 'M2C_FIELD' or _TYPE_END.search(name):
            continue
        depth, at = 1, hit.end()
        while at < len(text) and depth:
            depth += (text[at] == '(') - (text[at] == ')')
            at += 1
        found.append(text[hit.end():at - 1])
    return found


def _fields(text):
    """{(field, base)}: every field a piece of C names, a member by its name and a raw access by its offset."""
    found = set()
    for pattern in (_M2C, _OFFSET):
        found.update((int(m[2].rstrip('uUlL'), 0), m[1]) for m in pattern.finditer(text))
    found.update((m[2], m[1]) for m in _MEMBER.finditer(text))
    return found


class _Store:
    def __init__(self, field, base, reads, locals_, constant):
        self.field, self.base, self.reads, self.locals, self.constant = field, base, reads, locals_, constant


def _store(text):
    """A plain `field = value;` store with a value that has no call, assignment or step; otherwise None."""
    body = text.strip().rstrip(';').strip()
    hits = list(_ASSIGNS.finditer(body))
    if len(hits) != 1 or '++' in body or '--' in body or _calls(body):
        return None
    left, right = body[:hits[0].start()].strip(), body[hits[0].end():].strip()
    written = _fields(left)
    if len(written) != 1:
        return None
    (field, base), = written
    reads = {key for key, _ in _fields(right)}
    constant = bool(re.fullmatch(rf'-?\s*(?:{NUMBER}|[0-9]*\.[0-9]+f?)', right))
    return _Store(field, base, reads, set(re.findall(IDENT, right)) | {base}, constant)


def _independent(one, two):
    return one.field != two.field and one.field not in two.reads and two.field not in one.reads


def _pair_moves(stores):
    """Every order of the run in which two adjacent stores sit elsewhere among their neighbouring stores."""
    found = []
    count = len(stores)
    for first in range(count - 1):
        pair = (first, first + 1)
        if not all(stores[k] for k in pair):
            continue
        for step in (-1, 1):
            at = first if step < 0 else first + 1
            passed = []
            while True:
                at += step
                if not 0 <= at < count or not stores[at]:
                    break
                if not all(_independent(stores[k], stores[at]) for k in pair):
                    break
                passed.append(at)
                order = [k for k in range(count) if k not in pair]
                slot = order.index(at) + (1 if step > 0 else 0)
                order[slot:slot] = pair
                found.append((len(passed), first, tuple(order)))
    found.sort(key=lambda item: item[:2])
    return list(dict.fromkeys(order for _, _, order in found))


def _sinks(texts, stores):
    """[(index, [statements it may follow])]: each literal store with a call statement below it in the run."""
    found = []
    for index, store in enumerate(stores):
        if not store or not store.constant:
            continue
        places, called = [], False
        named = re.compile(rf'\b{re.escape(store.base)}\b')
        for later in range(index + 1, len(texts)):
            text = texts[later]
            if any(field == store.field for field, _ in _fields(text)):
                break
            calls = _calls(text)
            if any(named.search(arguments) for arguments in calls):
                break
            if re.search(rf'\b{re.escape(store.base)}\s*=(?!=)', text):
                break
            called = called or bool(calls)
            if called:
                places.append(later)
        if places:
            found.append((index, places))
    return found


def _rebuild(source, run, order):
    child = source[:run[0][0]]
    for slot, index in enumerate(order):
        gap = source[run[slot - 1][1]:run[slot][0]] if slot else ''
        child += gap + source[run[index][0]:run[index][1]]
    return child + source[run[-1][1]:]


def _sunk(order, index, after):
    order = [k for k in order if k != index]
    order.insert(order.index(after) + 1, index)
    return tuple(order)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean[part.opening:part.end]):
        return []
    combined, pairs = [], []
    stop = part.clean.rindex('}', part.opening, part.end)
    for run in _runs(part.clean, part.opening + 1, stop):
        texts = [part.clean[s:e] for s, e in run]
        stores = [_store(text) for text in texts]
        moves = _pair_moves(stores)
        identity = tuple(range(len(run)))
        pairs += [_rebuild(source, run, order) for order in moves]
        for index, places in _sinks(texts, stores):
            # only pairs below the call the constant crosses: the later run is the one it joins
            below = [m for m in moves if m[:places[0] + 1] == identity[:places[0] + 1]]
            for order in [identity] + below:
                combined += [_rebuild(source, run, _sunk(order, index, after)) for after in places]
    result, seen = [], {source}
    for family, children, limit in ((FAMILY, combined, LIMIT), (FAMILY_PAIR, pairs, PAIR_LIMIT)):
        taken = 0
        for child in children:
            if child not in seen and taken < limit:
                seen.add(child)
                result.append((family, child))
                taken += 1
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
