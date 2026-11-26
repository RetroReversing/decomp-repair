"""Separate stack locals that one call receives as a single block, declared as that block: one word array.

m2c splits a frame object it cannot see whole into the pieces it saw stored: a small array at `0x10($sp)`, a pointer
local at `0x18`, a bigger array from `0x1C`, and calls the function with the first one's address

    s32 sp10[2];  M2C_UNK *sp18;  s32 sp1C[14];
    sp10[0] = 0; sp10[1] = 0x18; sp18 = &D_800A7CE0; sp1C[1] = 0xC; sp1C[2] = arg0; ...
    g(sp10);

The game declared one array (`s32 buf[16];`) and filled it. As separate objects the pointer local is only ever read by a
test the compiler folds away, so its store (the word at `0x18($sp)` the callee reads) is dead and gone, and the
elements the C never named leave a hole, so the frame, the callee's block and every later store are one slot out. A
KMC GCC 2.7.2 N64 function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 35 instructions) stood at 110 with that C and at 0 with
`s32 buf[16]; buf[0] = 0; buf[1] = 0x18; buf[2] = (s32) &D_800A7CE0; buf[3] = 0xC; ...; g(buf);` (the stores in the
order m2c already wrote them, so no store-order search was needed once the objects were one).

This module finds the block: the lowest local whose address escapes (an array's bare name or `&spNN`), and the locals
declared at the offsets directly above it, each a word (`s32`, `u32`, `M2C_UNK`, or a pointer), a scalar or an array.
Two children, since `spNN` names show where m2c saw a store, not how the game laid the object out:
- by offset: element `(offset - first) / 4`, holes kept (an array element nobody names stays a slot);
- compact: the same, with every array element the C never indexes dropped (only offered when there is one).
A pointer local's assignment becomes a store of its value cast to `s32`, and its reads cast back. Nothing is offered
when a block member is a float or a halfword type, a pointer local's address is taken or it is updated in place, an
array is used other than by its bare name or a literal index while a compact layout is wanted, or fewer than two
locals form the block. A third child covers a block with holes: members with unnamed bytes between them (a scalar at `0x18`, the next local at
`0x2C`, a `char frame_pad[8];` a search declared in between) are the start and the tail of one object the C filled in
two steps (`buf[5..7]` stored after the call that filled `buf[0..4]`). `spNN` offsets give the slots, the gap
(at most 0x20 bytes) stays unnamed and the padding declarations go: an N64 camera helper (KMC GCC 2.7.2) with
`s32 sp18; char frame_pad[8]; s32 sp2C[3];` stood at 4 and was exact with `s32 sp18[8];`, the call receiving `sp18` and
the later stores `sp18[5..7]` (4 -> 0).
A candidate for the judge, never a verdict; the frame it makes is a hypothesis about the
game's object, not read from the compiler.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stack_locals_one_array'
FAMILIES = (FAMILY,)

WORDS = {'s32', 'u32', 'M2C_UNK', 'M2C_UNK32', 'int', 'unsigned', 'long'}
DECL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<type>[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*?)(?P<star>[ \t]*\*+[ \t]*|[ \t]+)'
                  r'sp(?P<off>[0-9A-Fa-f]+)(?:\[(?P<count>\d+)\])?[ \t]*;[ \t]*\n')


# the frame padding a search adds beside the locals (`char frame_pad[8];`): bytes nobody named
PAD = re.compile(r'(?m)^[ \t]*(?:char|u8|s8)[ \t]+(?:frame_pad|pad\w*)\[\d+\];[ \t]*\n')
GAP = 0x20  # the most bytes between two members that one array may span


def _members(body):
    """Declared word locals as (offset, text type, is pointer, element count or None, match), by offset."""
    found = []
    for m in DECL.finditer(body):
        typ = ' '.join(m['type'].split())
        pointer = '*' in m['star']
        if typ.split()[0] in ('return', 'else', 'goto', 'typedef') or not (pointer or typ in WORDS):
            continue
        found.append((int(m['off'], 16), typ, pointer, int(m['count']) if m['count'] else None, m))
    return sorted(found, key=lambda x: x[0])


def _block(members, bare, gap=0):
    """The contiguous word locals from the lowest escaped one upward (`bare` has the declarations blanked). With `gap`
    bytes, a hole of up to that size between two members (the bytes the C never named) does not end the block."""
    by_off = {}
    for item in members:
        by_off.setdefault(item[0], item)
    for off, typ, pointer, count, m in members:
        name = 'sp' + m['off']
        escaped = re.search(r'&\s*' + name + r'\b', bare)
        if not (escaped or (count and re.search(r'(?<![\w.>])' + name + r'\b(?!\s*\[)', bare))):
            continue
        if pointer and not count and escaped:
            return []
        block, nxt = [], off
        while True:
            if nxt not in by_off and gap:
                later = [o for o in by_off if nxt < o <= nxt + gap and o % 4 == nxt % 4]
                nxt = min(later) if later else nxt
            if nxt not in by_off:
                break
            item = by_off[nxt]
            block.append(item)
            nxt += 4 * (item[3] or 1)
        return block if len(block) >= 2 else []
    return []


def _referenced(bare, block):
    """Per array the indexes the C names (None: some use is not a literal index)."""
    used = {}
    for off, typ, pointer, count, m in block:
        if not count:
            continue
        hits = set()
        for use in re.finditer(r'(?<![\w.>])sp' + m['off'] + r'\b(?:\s*\[\s*(\d+)\s*\]|(\s*\[))?', bare):
            if use[2]:  # an index that is not a literal
                hits = None
                break
            if use[1]:
                hits.add(int(use[1]))  # (a bare name is the block's address, not an element)
        used[off] = hits
    return used


def _layout(block, used, compact):
    """Slot of each (offset, index) of the block, and the array's size."""
    slots, at = {}, 0
    for off, typ, pointer, count, m in block:
        for i in range(count or 1):
            if compact and count and i not in used[off]:
                continue
            slots[(off, i)] = at
            at += 1
    return slots, at


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    members = _members(body)
    bare = body
    for *_, m in members:
        bare = bare[:m.start()] + re.sub(r'\S', ' ', m[0]) + bare[m.end():]
    out = []
    plain = _block(members, bare)
    for block, hole in ((plain, False), (_block(members, bare, GAP), True)):
        if not block or (hole and [m[0] for m in block] == [m[0] for m in plain]):
            continue
        out += _children(source, opening, body, bare, block, hole)
    return [(FAMILY, text) for text in dict.fromkeys(out)]


def _children(source, opening, body, bare, block, hole):
    """The rewrites of one block: `hole` keeps every byte between its members as an array slot (the padding the
    search declared there goes), else the contiguous layouts (all slots, then only those the C indexes)."""
    used = _referenced(bare, block)
    gaps = any(count and used[off] is not None and len(used[off]) < count for off, _, _, count, _ in block)
    first = block[0]
    out = []
    for compact in ([False, True] if gaps and not hole else [False]):
        if compact and any(used[off] is None for off, _, _, count, _ in block if count):
            continue
        if hole:
            slots = {(off, i): (off - first[0]) // 4 + i for off, _, _, count, _ in block for i in range(count or 1)}
            last = block[-1]
            size = (last[0] - first[0]) // 4 + (last[3] or 1)
        else:
            slots, size = _layout(block, used, compact)
        elem = 'u32' if all(typ == 'u32' and not pointer for _, typ, pointer, _, _ in block) else 's32'
        buf = 'sp' + first[4]['off']
        edits = [(opening + m.start(), opening + m.end(),
                  f"{m['indent']}{elem} {buf}[{size}];\n" if off == first[0] else '')
                 for off, _, _, _, m in block]
        if hole:
            edits += [(opening + pad.start(), opening + pad.end(), '') for pad in PAD.finditer(body)]
        ok = True
        for off, typ, pointer, count, m in block:
            for use in re.finditer(r'(&\s*)?(?<![\w.>])sp' + m['off'] + r'\b(?:\s*\[\s*(\d+)\s*\])?', bare):
                s, e = opening + use.start(), opening + use.end()
                if count:
                    if use[2] is None:
                        slot = slots[(off, 0)]
                        edits.append((s, e, buf if slot == 0 else f'&{buf}[{slot}]'))
                        continue
                    slot = slots.get((off, int(use[2])))
                    if slot is None:
                        ok = False
                        break
                    edits.append((s, e, ('&' if use[1] else '') + f'{buf}[{slot}]'))
                    continue
                slot = slots[(off, 0)]
                if use[1]:
                    edits.append((s, e, buf if slot == 0 else f'&{buf}[{slot}]'))
                elif not pointer:
                    edits.append((s, e, f'{buf}[{slot}]'))
                else:
                    tail = bare[use.end():]
                    head = bare[:use.start()].rstrip()
                    assign = re.match(r'\s*=(?!=)\s*([^;]*);', tail)
                    if assign and head[-1:] in (';', '{', '}'):
                        edits.append((s, opening + use.end() + assign.end(),
                                      f'{buf}[{slot}] = ({elem}) ({assign[1].strip()});'))
                    elif re.match(r'\s*(?:[-+*/|&^]|<<|>>)=|\s*(?:\+\+|--)', tail) or head.endswith(('++', '--')):
                        ok = False
                        break
                    else:
                        edits.append((s, e, f'(({typ} {m["star"].strip()}) {buf}[{slot}])'))
            if not ok:
                break
        if not ok:
            continue
        text = source
        for a, b, rep in sorted(set(edits), reverse=True):
            text = text[:a] + rep + text[b:]
        if text != source and text not in out:
            out.append(text)
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
