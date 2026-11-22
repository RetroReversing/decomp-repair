"""Float locals written through a `union { f32 f; u32 i; }` pun, written as plain floats, with the scalar locals re-declared.

A 178-instruction ray-and-triangle test (N64, KMC GCC 2.7.2, `-O2 -G0 -mips3 -mgp32 -mfp32`) sat at 275 with only
register rows left (55 of them) after earlier sessions forced five float locals into integer registers: each was a
`FU` union (`ex.f = a - b; e2[0] = ex.i;`, the vectors read back as `((FU *) p)[1]`) and the stack copies were a `u32`
array. The target holds those five floats in integer registers too, but because the allocator put them there, not
because the source said so. With plain `f32` locals (`ex = a - b; e2.x = ex;`, `dy = p->y;`) the score went 275 -> 100,
and the remaining rows were an allocation tie: GCC 2.7.2's global allocator (global.c) takes the registers in order of
`floor_log2(uses) * uses / live_length` and breaks equal priorities by pseudo number, and a pseudo's number is the
place of its declaration. Two pairs tied here (a stored component and a loaded component of equal use counts and
lengths), the wrong one of each pair came first, so the allocator's callee-saved float registers went to the wrong
locals, and the two that lost them to the reload's spill of two register pairs went to integer registers. Declaring
the three differences before the loaded components gave 0 (the same set of declarations in the other orders also,
275 -> 0 from the saved best in two edits, neither alone: the de-punned locals with the declarations unchanged 100,
the declarations moved with the unions in place 275). The compiler's explanation (priority ties broken by pseudo number,
a spilled pair evicting two floats to integer registers) is read from `-dl -dg` dumps, a hypothesis, not from the
compiler's source.

Variants: every pun local whose every use is `x.f`, `x.i` stored into a local integer array that is only ever stored
to, or an assignment from a pun-typed load, becomes a plain `f32` (the array an `f32` array, the casts `(f32 *)`); then
the same with each non-empty subset of the plain float locals declared after the pun group moved before it, since the
declaration order is what the allocator's ties follow.
"""
import re
from itertools import combinations

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_pun_depun'
FAMILIES = (FAMILY,)

UNION = re.compile(r'typedef\s+union\s*\w*\s*\{([^{}]*)\}\s*(\w+)\s*;')
MEMBER = re.compile(r'\b(f32|float|u32|s32|int|unsigned(?:\s+int)?)\s+(\w+)\s*;')
FLOATS = ('f32', 'float')
INTEGER = r'(?:u32|s32|int|unsigned(?:\s+int)?)'
DECLARATION = re.compile(r'(?m)^([ \t]*)(\w[\w ]*?)[ \t]+(\w+(?:[ \t]*,[ \t]*\w+)*)[ \t]*;[ \t]*\n')
MAX_MOVABLE = 5


def _puns(source):
    """{typedef name: (float member, integer member)} of the unions that overlay one float and one integer."""
    found = {}
    for union in UNION.finditer(_blank(source)):
        members = MEMBER.findall(union[1])
        floats = [n for t, n in members if t in FLOATS]
        ints = [n for t, n in members if t not in FLOATS]
        if len(members) == 2 and len(floats) == 1 and len(ints) == 1:
            found[union[2]] = (floats[0], ints[0])
    return found


def _arrays(cbody, name, integer, skip):
    """The integer arrays the pun local's integer half is stored into, or None when it is used any other way.

    `skip` holds the spans of the declarations. Allowed: `.float` anywhere, `arr[i] = x.int;`, and the whole pun
    assigned from a pun-typed load or another pun local."""
    flo_or_int = re.compile(r'\.(\w+)\b')
    arrays, stores = set(), 0
    for use in re.finditer(rf'(?<![\w.>]){name}\b', cbody):
        if any(a <= use.start() < b for a, b in skip):
            continue
        member = flo_or_int.match(cbody, use.end())
        if member:
            if member[1] == integer:
                store = re.search(rf'(\w+)\s*\[[^\]\n]+\]\s*=\s*{name}\.{integer}\s*;', cbody[max(0, use.start() - 80):use.end() + 3])
                if not store:
                    return None
                arrays.add(store[1])
                stores += 1
            continue
        if re.match(r'\s*=(?!=)', cbody[use.end():use.end() + 3]):
            rhs = cbody[use.end():cbody.find(';', use.end())]
            if re.search(r'\(\s*\w+\s*\*\s*\)', rhs) or re.search(r'\b\w+\b', rhs):
                continue
        return None
    return arrays


def _array_ok(cbody, array, skip_decl):
    """The array is declared as a plain integer array and only ever stored to by `arr[i] = pun.int`."""
    decl = re.search(rf'(?m)^[ \t]*{INTEGER}[ \t]+{array}\s*\[\d+\]\s*;', cbody)
    if not decl:
        return False
    total = [m for m in re.finditer(rf'(?<![\w.>]){array}\b', cbody) if not decl.start() <= m.start() < decl.end()]
    stores = re.findall(rf'(?<![\w.>]){array}\s*\[[^\]\n]+\]\s*=\s*\w+\.\w+\s*;', cbody)
    return len(total) == len(stores)


def variants(source, name):
    span = find(source, name)
    puns = _puns(source)
    if not span or not puns:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or (end := close(clean, opening, '{', '}')) is None:
        return []
    body, cbody = source[opening:end], clean[opening:end]
    decls = [(d.start(), d.end(), d[1], d[2].strip(), [n.strip() for n in d[3].split(',')]) for d in DECLARATION.finditer(cbody)]
    groups = [d for d in decls if d[3] in puns]
    if not groups:
        return []
    skip = [(d[0], d[1]) for d in groups]
    done, arrays = {}, set()
    for _, _, _, kind, names in groups:
        for n in names:
            used = _arrays(cbody, n, puns[kind][1], skip)
            if used is not None and all(_array_ok(cbody, a, skip) for a in used):
                done[n] = kind
                arrays |= used
    if not done:
        return []
    movable = [n for d in decls if d[0] > groups[0][0] and d[3] in FLOATS and d not in groups for n in d[4]][:MAX_MOVABLE]
    found = []

    def build(moved):
        edits = {}
        for start, stop, indent, kind, names in groups:
            keep = [n for n in names if n not in done]
            new = f'{indent}f32 {", ".join(n for n in names if n in done)};\n' if len(keep) != len(names) else ''
            new += f'{indent}{kind} {", ".join(keep)};\n' if keep else ''
            edits[start] = (stop, new)
        if moved:
            stop, new = edits[groups[0][0]]
            edits[groups[0][0]] = (stop, f'{groups[0][2]}f32 {", ".join(moved)};\n' + new)
            for d in decls:
                if d[0] > groups[0][0] and d[3] in FLOATS and d not in groups and any(n in moved for n in d[4]):
                    rest = [n for n in d[4] if n not in moved]
                    edits[d[0]] = (d[1], f'{d[2]}f32 {", ".join(rest)};\n' if rest else '')
        out, cursor = [], 0
        for start in sorted(edits):
            stop, new = edits[start]
            out.append(body[cursor:start] + new)
            cursor = stop
        text = ''.join(out) + body[cursor:]
        for n, kind in done.items():
            text = re.sub(rf'(?<![\w.>]){n}\.(?:{puns[kind][0]}|{puns[kind][1]})\b', n, text)
        for kind in puns:
            text = re.sub(rf'\(\s*{kind}\s*\*\s*\)', '(f32 *)', text)
        for array in arrays:
            text = re.sub(rf'(?m)^([ \t]*){INTEGER}([ \t]+{array}\s*\[\d+\]\s*;)', r'\1f32\2', text)
        return text

    candidates = [()]
    for size in range(1, len(movable) + 1):
        candidates += list(combinations(movable, size))
    for moved in candidates:
        candidate = source[:opening] + build(list(moved)) + source[end:]
        if candidate != source and (FAMILY, candidate) not in found:
            found.append((FAMILY, candidate))
    return found
