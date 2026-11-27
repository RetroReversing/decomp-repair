"""A computed value and the store of it, moved together past the independent statements around them.

An N64 effect update (SN GCC 2.8.1, `-G0 -mips3 -O2 -mgas`, 33 instructions) bumped a record's counter, advanced its
phase, wrote three shade bytes and a halfword height, then compared the height. The search's best computed the height
last, after the shade bytes:

    do {
        t = *(s32 *)(p + 0x34) + 1;  *(s32 *)(p + 0x34) = t;
        phase = *(s32 *)(p + 0x3C) + K;  *(s32 *)(p + 0x3C) = phase;
        ...three byte stores...
        h = *(u16 *)(p + 0x3A) + (t >> 1);  *(s16 *)(p + 0x6A) = h;
        if ((h & 0xFFFF) > ...) { ... }
    } while (0);

The target loads the height's operand right after the counter, so the game computed and stored the height before the
phase, and tested the member. The two statements move as one (`statement_slide` moves one statement, four places at
most), and it only pays off with the compare reading the member back and the one-shot fences opened: the move alone
scored 120 -> 300, the read-back alone 955, the fences alone 180, all three together 0.

A proposal takes `t = E;` directly followed by `M = t;` for a plain local `t`, and moves both to another place in the
same run of straight-line statements where every statement passed commutes with both (`statement_slide.commutes`: no
call, no overlapping cell, no shared local written). It is offered on the source as written, with the later reads of
`t` written as the member (`stored_member_readback`), and with every one-shot fence opened, the combinations first.
This module reads text only and never compiles or judges."""
from .hand_found_support import store_target
from .integer_repair_support import view
from .statement_slide import _locals, _runs, commutes
from .stored_member_readback import _readbacks, _unfence

FAMILY = 'stored_pair_slide'
READBACK = 'stored_pair_slide_readback'
FAMILIES = (FAMILY, READBACK)
REACH = 8  # statements a pair may pass
LIMIT = 24  # children per form of the source


def _moves(source, name):
    """`source` with one computed-and-stored pair elsewhere in its run, farthest moves up first, then down."""
    part = view(source, name)
    if not part:
        return []
    safe = _locals(part)
    found = []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end)):
        texts = [source[start:end] for start, end in run]
        parsed = [store_target(part.clean[start:end]) for start, end in run]
        for index in range(len(run) - 1):
            first, second = parsed[index], parsed[index + 1]
            if not first or not second or first[0] not in safe or second[1] != first[0]:
                continue
            if second[0].strip() in safe:  # a copy between locals is no store
                continue
            pair = texts[index:index + 2]
            for sign in (-1, 1):
                for step in range(1, REACH + 1):
                    passed = index - step if sign < 0 else index + 1 + step
                    if not 0 <= passed < len(run) or not all(commutes(one, texts[passed]) for one in pair):
                        break
                    order = [k for k in range(len(run)) if k not in (index, index + 1)]
                    at = index - step if sign < 0 else index + step
                    order[at:at] = [index, index + 1]
                    child = source[:run[0][0]]
                    for place, k in enumerate(order):
                        gap = source[run[place - 1][1]:run[place][0]] if place else ''
                        child += gap + texts[k]
                    child += source[run[-1][1]:]
                    found.append((sign, -step, child))
    return list(dict.fromkeys(child for _, _, child in sorted(found, key=lambda item: item[:2])))[:LIMIT]


def variants(source, name):
    """Proposals: the pair moved, with the member read back and the one-shot fences opened where they apply."""
    opened = _unfence(source, name)
    forms = [base for base in (opened, source) if base]
    out = []
    for base in forms:
        for read in _readbacks(base, name)[:2]:
            out += [(READBACK, child) for child in _moves(read, name)]
    for base in forms:
        out += [(FAMILY, child) for child in _moves(base, name)]
    seen = {source}
    return [(family, child) for family, child in out if not (child in seen or seen.add(child))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
