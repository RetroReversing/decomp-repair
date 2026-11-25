"""A store to the next field of a record, gathered beside the store before it.

m2c writes a run of stores through one record pointer in the order it met the values, so a field whose value is
computed from floats (`o->z = arg0->z + (f32) d;`) lands after the constant stores that were scheduled between the
x/y stores and the call, and an agent editing the draft keeps that order. The game's source stored the position as
one group: `o->x`, `o->y`, `o->z`, then the constants. GCC 2.7.2's scheduler breaks ties by the original insn order
and the allocator numbers pseudos by first use, so the position's three stores (and the constants' registers) come
out in the target's order only when the three statements stand together. A KMC GCC 2.7.2 N64 object spawner (a
record from an allocation call, then thirty stores) stood at 1621 with `o->z` after `o->f7C = 1;` and at 0 with it
directly after `o->y`: a move of four places that `store_run_order` (adjacent swaps, to the front, to the back) and
`member_store_hoist` do not make.

For each run of simple statements the store model of `store_run_order` understands (a call, a branch or a label ends a
run), a store whose cell sits right after another store's cell of the same base (`z` at 0xC after `y` at 8) is moved
to stand directly after it, and one whose cell sits right before another's is moved directly before it. Cells are read
from `M2C_FIELD(base, type *, off)`, the cast spellings and `base->member` (the member's offset from the record the
base is declared as, read from a `struct` in the source or the header). A child is offered only when the moved store
commutes with every statement it passes (`store_run_order.Effects`), so it is the same program. Hypothesis from one
match; the judge decides. Bounded to `LIMIT` children, shortest moves first.
"""
import re

from .integer_repair_support import IDENT, view
from .store_run_order import _WIDTH, _clash, _names, _rebuild, _records, _segments

FAMILY = 'store_adjacent_gather'
FAMILIES = (FAMILY,)
LIMIT = 8

_STRUCT = re.compile(rf'(?:typedef\s+)?struct\s*(?P<tag>{IDENT})?\s*\{{(?P<body>[^{{}}]*)\}}\s*(?P<alias>{IDENT})?\s*;')
_MEMBER = re.compile(rf'^(?P<type>[^()\[\]]*?)[\s*]+(?P<name>{IDENT})\s*(?:\[\s*(?P<count>0[xX][0-9a-fA-F]+|\d+)\s*\])?$')
_FUNCTION_POINTER = re.compile(rf'\(\s*\*\s*(?P<name>{IDENT})\s*\)')


def _size(type_text, pointer):
    if pointer:
        return 4
    words = [word for word in type_text.split() if word not in ('const', 'volatile', 'unsigned', 'signed', 'struct')]
    for word in reversed(words):
        if word in _WIDTH:
            return _WIDTH[word]
    if type_text.split()[:1] == ['unsigned'] or type_text.split()[:1] == ['signed']:
        return 4
    return None


def layouts(text):
    """{record name: {member: (offset, width)}} of the plain records in `text` (scalars, pointers, arrays of them);
    a record with a member of another kind is left out."""
    found = {}
    text = re.sub(r'/\*.*?\*/|//[^\n]*', ' ', text, flags=re.S)
    for hit in _STRUCT.finditer(text):
        members, offset, ok = {}, 0, True
        for declaration in hit['body'].split(';'):
            declaration = declaration.strip()
            if not declaration:
                continue
            pointer = bool(_FUNCTION_POINTER.search(declaration))
            if pointer:
                name, count, width = _FUNCTION_POINTER.search(declaration)['name'], None, 4
            else:
                member = _MEMBER.match(declaration)
                if not member:
                    ok = False
                    break
                name, count = member['name'], member['count']
                width = _size(member['type'], '*' in declaration.split(name)[0])
                if width is None:
                    ok = False
                    break
            align = min(width, 4)
            offset += -offset % align
            members[name] = (offset, width)
            offset += width * (int(count, 0) if count else 1)
        if ok:
            for key in (hit['tag'], hit['alias']):
                if key:
                    found[key] = members
    return found


def _variable_types(part, source):
    """{variable: record name} for the `Rec *name` parameters and locals of the function."""
    head = source[:part.opening]
    signature = head[head.rfind('(', 0, part.opening):part.opening] if '(' in head else ''
    body = part.clean[part.opening:part.end]
    return {hit['name']: hit['type'] for hit in re.finditer(
        rf'(?:struct\s+)?(?P<type>{IDENT})\s*\*\s*(?P<name>{IDENT})\s*(?=[,;)=])', signature + '\n' + body)}


def _placed(effects, types, records):
    """(base, low, high) of a store's cell, or None when its offset is not known."""
    base, family, low, high = effects.store
    if family == 'off':
        return base, low, high
    if family == 'member':
        member = records.get(types.get(base), {}).get(low)
        if member:
            return base, member[0], member[0] + member[1]
    return None


def _fresh(part):
    """The pointer locals assigned once, from a call (`o = allocate(...);`): a new object no other pointer names."""
    body = part.clean[part.opening:part.end]
    found = set()
    for hit in re.finditer(rf'(?m)^[ \t]*(?P<name>{IDENT})\s*=\s*(?:\([^()]*\)\s*)?{IDENT}\s*\(', body):
        name = hit['name']
        if len(re.findall(rf'(?<![\w.>])\s*{name}\s*=(?!=)', body)) == 1:
            found.add(name)
    return found


def _commutes(one, other, fresh):
    """`Effects.commutes`, except that a cell of a fresh pointer is told apart from a cell of any other base."""
    def clash(a, b):
        if a[0] == 'c' and b[0] == 'c' and a[1] != b[1] and (a[1] in fresh or b[1] in fresh):
            return False
        return _clash(a, b)
    return not (any(clash(w, k) for w in one.writes for k in other.writes | other.reads)
                or any(clash(w, k) for w in other.writes for k in one.reads))


def _children(source, groups, types, records, fresh):
    ranked = []
    for number, group in enumerate(groups):
        effects = [item[2] for item in group]
        cells = [_placed(item, types, records) if item.kind == 'store' else None for item in effects]
        for index, mine in enumerate(cells):
            if not mine:
                continue
            for other, theirs in enumerate(cells):
                if other == index or not theirs or theirs[0] != mine[0]:
                    continue
                if mine[1] == theirs[2]:
                    after = True  # directly after `other`
                elif mine[2] == theirs[1]:
                    after = False  # directly before `other`
                else:
                    continue
                order = list(range(len(group)))
                order.pop(index)
                anchor = order.index(other)
                order.insert(anchor + 1 if after else anchor, index)
                if order == sorted(order):
                    continue
                crossed = [k for k in range(len(group)) if k != index
                           and (order.index(k) < order.index(index)) != (k < index)]
                if not all(_commutes(effects[index], effects[k], fresh) for k in crossed):
                    continue
                ranked.append((len(crossed), number, tuple(order), group))
    result = []
    for _, _, order, group in sorted(ranked, key=lambda item: item[:3]):
        child = _rebuild(source, group, order)
        if child != source and child not in result:
            result.append(child)
        if len(result) >= LIMIT:
            break
    return result


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean[part.opening:part.end]):
        return []
    text = header + '\n' + source
    records = layouts(text)
    names = _names(part, source)
    groups = _segments(source, part, names, _records(text))
    types = _variable_types(part, source)
    return [(FAMILY, child) for child in _children(source, groups, types, records, _fresh(part))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
