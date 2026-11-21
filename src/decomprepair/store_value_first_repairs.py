"""A converted value computed into a local before the store that uses it, so the value is scheduled ahead of the address.

gcc 2.7.2 expands `lhs = rhs;` with the left side's address first: for `rs->vp[i].h[4] = (s16)(f * 4.0f);` the load
of `rs` and the index arithmetic come ahead of the float multiply, the truncation and the move to an integer
register, and the first scheduler keeps ties in that order. m2c writes such a store as `temp = (s16)(...);
*(addr) = temp;` when it wants the value in a register first, and the game's own source often did too. On a
twenty-statement N64 camera function (KMC gcc 2.7.2) sixteen stores of float-to-short values through a global pointer's
viewport array, each written with a temporary, took the function from 815 to 90 (all of them; two segments of three
gave 390): the load of the pointer moved below the multiply as the target has it. The judge ruled out each store
alone as too little, so besides every store and each store alone, this offers the stores a run at a time.

Offered for an assignment whose left side goes through a pointer or array (`->`, `.` or `[`) and whose right side is
a cast of an expression with a floating operation and no call. A local of the cast's type holds the value.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'store_value_first'
FAMILIES = (FAMILY,)
LIMIT = 12
CASTS = r'(?:s8|u8|s16|u16|s32|u32|int|short|char|float|f32|unsigned\s+(?:char|short|int))'
STORE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<lhs>{IDENT}[^;=\n]*(?:->|\.|\[)[^;=\n]*?)\s*=(?!=)\s*'
                   rf'\((?P<type>{CASTS})\)\s*(?P<rhs>[^;\n]+);[ \t]*$')
FLOATING = re.compile(r'\b(?:f32|float|double)\b|\b\d+\.\d*f?\b|\b\d+f\b')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    base = part.opening + 1
    stores = []
    for match in STORE.finditer(part.body):
        rhs = match['rhs']
        if re.search(rf'{IDENT}\s*\(', re.sub(rf'\(\s*{CASTS}\s*\)', '', rhs)):
            continue  # a call: its order against the address is not ours to change
        if not FLOATING.search(rhs) or '++' in rhs or '--' in rhs or re.search(r'(?<![=!<>])=(?!=)', rhs):
            continue
        stores.append(match)
    if not stores:
        return []
    taken = set(re.findall(r'\btv\d+\b', part.clean))
    names = iter(f'tv{n}' for n in range(1, 10 ** 4) if f'tv{n}' not in taken)

    def rewrite(chosen):
        edits, declarations = [], []
        for match in chosen:
            local = next(names)
            declarations.append(f'  {match["type"]} {local};')
            edits.append((base + match.start(), base + match.end(),
                          f'{match["indent"]}{local} = ({match["type"]}) {match["rhs"]};\n'
                          f'{match["indent"]}{match["lhs"]} = {local};'))
        edits.append((base, base, '\n' + '\n'.join(declarations)))
        return edit(source, edits)

    chosen = [stores]
    chosen += [[match] for match in stores[:4]] if len(stores) > 1 else []
    run = [stores[0]]
    for match in stores[1:]:  # a run: stores with only other statements between them, split at blank code
        gap = part.body[run[-1].end():match.start()]
        if gap.count(';') <= 1:
            run.append(match)
        else:
            if len(run) > 1 and run != stores:
                chosen.append(run)
            run = [match]
    if len(run) > 1 and run != stores:
        chosen.append(run)
    seen, result = set(), []
    for group in chosen:
        key = tuple(match.start() for match in group)
        if key not in seen:
            seen.add(key)
            names = iter(f'tv{n}' for n in range(1, 10 ** 4) if f'tv{n}' not in taken)
            result.append((FAMILY, rewrite(group)))
    return result[:LIMIT]
