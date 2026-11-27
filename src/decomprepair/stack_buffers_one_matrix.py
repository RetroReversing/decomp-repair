"""Equal stack buffers at consecutive offsets, which one callee fills in turn, declared as one two-dimensional array.

m2c names each frame object it saw by the offset it was stored at, and a callee that fills `buf[i]` for four calls in a row
becomes four separate arrays plus a scalar for the word the loop reads first:

    s32 sp10[4];  char sp20[0x10];  u8 sp30[0x10];  u8 sp40[0x10];  s32 sp18;
    f(a + 0x18, sp10);  f(a + 0x20, sp20);  f(a + 0x28, sp30);  f(a + 0x30, sp40);   best = sp18;

The game declared `s32 buf[4][4];` and called `f(.., buf[0])` ... `f(.., buf[3])`, then read `buf[i][2]` in a loop. As
separate objects the frame is laid out in the order the compiler likes (and the word at `sp18` is a fifth object
overlapping the first), so every later store and read is one slot out and the loop's stride cannot be the row length.
The game's version of an SN GCC 2.7.2 `-O2` function that takes the largest of four results (240 -> 0 with the matrix,
a clean loop and a typed float store; `stack_locals_one_array` takes word locals only, never byte arrays).

Offered for two or more arrays `TYPE spHH[COUNT];` of a 1, 2 or 4 byte integer element, all the same size N (a multiple of
4) and at consecutive offsets (stride N), each used as a bare name (its address passed on). Each becomes row j of one
`s32 sp<first>_rows[K][N/4]` (the first's offset names it), a word scalar `spXX;` inside the block becomes its element,
and an array indexed `spHH[i]` is accepted only when its elements are words. A second child also reads the byte walk
`*(s32 *)((s8 *)rows[0] + i * N + K)` over the rows as `rows[i][K / 4]`. A hypothesis about the game's
declaration; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stack_buffers_one_matrix'
FAMILIES = (FAMILY,)
SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'M2C_UNK': 4,
         'M2C_UNK32': 4}
TYPE = '|'.join(sorted(SIZES, key=len, reverse=True))
ARRAY = re.compile(rf'(?m)^[ \t]*(?P<type>{TYPE})[ \t]+sp(?P<off>[0-9A-Fa-f]+)\[(?P<n>0x[0-9A-Fa-f]+|\d+)\][ \t]*;[ \t]*\n')
SCALAR = re.compile(r'(?m)^[ \t]*(?P<type>s32|u32|int|M2C_UNK)[ \t]+sp(?P<off>[0-9A-Fa-f]+)[ \t]*;[ \t]*\n')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    arrays = [(int(m['off'], 16), SIZES[m['type']] * int(m['n'], 0), SIZES[m['type']], m) for m in ARRAY.finditer(body)]
    arrays.sort(key=lambda a: a[0])
    run = []
    for at, start in enumerate(arrays):
        chain = [start]
        for item in arrays[at + 1:]:
            if item[1] != start[1] or item[0] != chain[-1][0] + item[1]:
                break
            chain.append(item)
        run = max(run, chain, key=len)
    if len(run) < 2 or run[0][1] % 4:
        return []
    first, size = run[0][0], run[0][1]
    words = size // 4
    matrix = f'sp{first:X}_rows'
    rows = {f'sp{off:X}': index for index, (off, *_rest) in enumerate(run)}
    spans = [(part.opening + a[3].start(), part.opening + a[3].end()) for a in run]
    scalars = [(int(m['off'], 16), m) for m in SCALAR.finditer(body)]
    inside = {f'sp{off:X}': (off - first) for off, _m in scalars if first <= off < first + size * len(run) and (off - first) % 4 == 0}
    spans += [(part.opening + m.start(), part.opening + m.end()) for off, m in scalars if f'sp{off:X}' in inside]
    edits = [(spans[0][0], spans[0][1], f'    s32 {matrix}[{len(run)}][{words}];\n')]
    edits += [(start, end, '') for start, end in spans[1:]]
    for hit in re.finditer(r'(?<![\w.>])(?P<n>sp[0-9A-Fa-f]+)\b(?P<idx>\s*\[)?', clean[part.opening:part.end]):
        start = part.opening + hit.start()
        if any(a <= start < b for a, b in spans):
            continue
        if hit['n'] in rows:
            if hit['idx'] and run[rows[hit['n']]][2] != 4:
                return []
            edits.append((start, start + len(hit['n']), f'{matrix}[{rows[hit["n"]]}]'))
        elif hit['n'] in inside and not hit['idx']:
            word = inside[hit['n']] // 4
            edits.append((start, start + len(hit['n']), f'{matrix}[{word // words}][{word % words}]'))
    text = edit(source, edits)
    # the game's `buf[i][2]` for m2c's byte walk `*(s32 *)((s8 *)buf[0] + i * 0x10 + 8)` over the rows
    walk = re.compile(rf'\*\(\s*s32\s*\*\)\(\(s8 \*\){matrix}\[0\]\s*\+\s*(?P<i>{IDENT}|\d+)\s*\*\s*(?P<n>0x[0-9A-Fa-f]+|\d+)\s*'
                      rf'\+\s*(?P<k>0x[0-9A-Fa-f]+|\d+)\)')
    rowed = walk.sub(lambda h: f'{matrix}[{h["i"]}][{int(h["k"], 0) // 4}]'
                     if int(h['n'], 0) == size and int(h['k'], 0) % 4 == 0 and int(h['k'], 0) < size else h[0], text)
    return [(FAMILY, text)] + ([(FAMILY, rowed)] if rowed != text else [])


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
