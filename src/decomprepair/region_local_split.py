"""One scratch local reused by two unrelated `goto` ladders, given a name per ladder.

m2c names a value by its register and reuses the name: `var_v0` holds the mode a first compare ladder picks
(`mark_84: state |= 0x2000; mode_84: var_v0 = 0x84; goto save;`) and, a few cases later, the mode a second ladder picks
with other bounds. One name is one pseudo register, live across both ladders' labels, so the allocator treated the
two as one value with the references of both: global.c ranked it above the type it was compared against and gave it
`$v1`, where the target had `$v0` for the mode and `$v1` for the type, and the type of the second ladder fell to `$a0`.
Split in two, each pseudo had its own range and the mode landed in `$v0`: 1675 -> 1370 on a 603-instruction N64 state
machine (KMC GCC 2.7.2), every register row of both ladders.

`local_web_split` splits a local per assignment web but leaves a web alone when a `goto` or a label sits inside it; the
ladders are made of them. This one takes a different region: the text of the switch body between two statements that
leave it (`return ...;` or `break;` directly in the switch's block), so no value can flow from one region into the
next, provided every `goto` of the function jumps to a label inside its own region and the first mention of the local in
the region is an assignment. Only a function-level scalar local without initialiser, array, `volatile` or `&name`.

Labelled `region_local_split`: the local renamed in every region after the first (`name_2`, `name_3`, declared beside it),
for each local; and every such local at once.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'region_local_split'
FAMILIES = (FAMILY,)
LIMIT = 8

_ID = r'[A-Za-z_]\w*'


def _switch_blocks(clean, opening, closing):
    """[(open, close)] of the blocks that are the body of a `switch (...)`."""
    out = []
    for m in re.finditer(r'\bswitch\s*\(', clean[opening:closing]):
        paren = close(clean, opening + m.end() - 1)
        if not paren:
            continue
        brace = re.compile(r'\s*\{').match(clean, paren)
        end = close(clean, brace.end() - 1, '{', '}') if brace else None
        if end:
            out.append((brace.end() - 1, end))
    return out


def _regions(clean, block):
    """The (start, end) spans of the switch block between statements that leave it."""
    start, end = block
    cuts, depth, at = [], 0, start + 1
    while at < end:
        ch = clean[at]
        depth += ch == '{'
        depth -= ch == '}'
        if depth == 0:
            m = re.compile(r'\b(?:return\b[^;{}]*|break)\s*;').match(clean, at)
            if m and (at == start + 1 or not re.match(r'[\w]', clean[at - 1])):
                cuts.append(m.end())
                at = m.end()
                continue
        at += 1
    spans, begin = [], start + 1
    for cut in cuts:
        spans.append((begin, cut))
        begin = cut
    if begin < end:
        spans.append((begin, end))
    return spans


def _declared(clean, opening, closing):
    names = {}
    head = clean[opening + 1:closing]
    for m in re.finditer(rf'(?m)^([ \t]*)((?:unsigned\s+|signed\s+|register\s+)*(?:u8|s8|u16|s16|u32|s32|int|long|short|char|unsigned|f32|float))\s+({_ID})\s*;', head):
        if 'volatile' in m[2]:
            continue
        names[m[3]] = (opening + 1 + m.start(), opening + 1 + m.end(), m[1], m[2])
    return names


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    blocks = _switch_blocks(clean, opening, closing)
    if not blocks:
        return []
    regions = []
    for block in blocks:
        regions.extend(_regions(clean, block))
    # every goto must stay in its own region
    labels = {m[1]: m.start() for m in re.finditer(rf'(?m)^[ \t]*({_ID})[ \t]*:(?!:)', clean[opening:closing])}
    labels = {k: opening + v for k, v in labels.items() if k not in ('default',)}

    def region_of(pos):
        return next((i for i, (a, b) in enumerate(regions) if a <= pos < b), None)
    entered = set()
    for m in re.finditer(rf'\bgoto\s+({_ID})\s*;', clean[opening:closing]):
        target = labels.get(m[1])
        if target is None:
            return []
        if region_of(opening + m.start()) != region_of(target):
            entered.add(region_of(target))
    declared = _declared(clean, opening, closing)
    plans = []
    for var, (_, declaration_end, indent, kind) in declared.items():
        if re.search(rf'&\s*{var}\b', clean[opening:closing]):
            continue
        used = []
        for index, (a, b) in enumerate(regions):
            mentions = [m for m in re.finditer(rf'(?<![\w.>]){var}\b', clean[a:b])]
            if mentions:
                used.append((index, a, b, mentions))
        used = used[:1] + [item for item in used[1:] if item[0] not in entered]
        if len(used) < 2:
            continue
        ok = True
        for _, a, b, mentions in used:
            first = mentions[0]
            if not re.match(r'\s*=(?!=)', clean[a + first.end():a + first.end() + 4]):
                ok = False
                break
        if ok:
            plans.append((var, declaration_end, indent, kind, used))

    def build(chosen):
        edits, declarations = [], []
        for var, declaration_end, indent, kind, used in chosen:
            for number, (_, a, b, mentions) in enumerate(used[1:], start=2):
                fresh = f'{var}_{number}'
                if re.search(rf'\b{fresh}\b', clean):
                    return None
                for m in mentions:
                    edits.append((a + m.start(), a + m.end(), fresh))
                declarations.append((declaration_end, f'\n{indent}{kind} {fresh};'))
        new = source
        for start, end, text in sorted(edits + [(at, at, text) for at, text in declarations], reverse=True):
            new = new[:start] + text + new[end:]
        return new

    out, seen = [], set()
    groups = [[plan] for plan in plans]
    if len(plans) > 1:
        groups.append(plans)
    for group in groups:
        new = build(group)
        if new and new != source and new not in seen:
            seen.add(new)
            out.append((FAMILY, new))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
