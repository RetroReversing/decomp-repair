"""A block copied word by word from one symbol, written as the struct assignment it was.

An SDK boot routine copies a 16-byte handler to each exception vector with a struct assignment. m2c has no record, so
it writes one store per word, to a constant address or to consecutive globals:

    D_80000000 = M2C_FIELD(&handler, s32 *, 0);
    D_80000004 = M2C_FIELD(&handler, s32 *, 4);
    ...
    M2C_FIELD((void *)0x80000080, s32 *, 0) = (s32) M2C_FIELD(&handler, s32 *, 0);
    M2C_FIELD((void *)0x80000080, s32 *, 4) = (s32) M2C_FIELD(&handler, s32 *, 4);

`word_block_copy` reads copies between two pointer variables only. gcc expands the struct assignment as a block move
(three words loaded, three stored, then the fourth), which one store per word never gives: in a 138-instruction N64
boot routine (KMC GCC 2.7.2 `-O2`) the four copies as assignments took the draft from 8700 to 2225, and with
`u64_pair_libcall`, direct stores in the branch arms and a stray argument dropped it was exact.

A run to consecutive globals is offered as the record at the first global's address and, when the name carries the
address (`D_80000000`), at that constant (the target loads one `lui` and stores off it). All runs are rewritten in one
child for each spelling. A candidate only: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'symbol_block_copy'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_WORD = r'(?:s32|u32|int|M2C_UNK|M2C_UNK32)'
_STORE = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?:M2C_FIELD\(\s*(?P<base>[^,;\n]+?)\s*,\s*{_WORD}\s*\*\s*,\s*(?P<off>{_NUM})\s*\)'
    rf'|(?P<sym>D_[0-9A-Fa-f]{{8}}))\s*=\s*(?:\(\s*{_WORD}\s*\)\s*)?'
    rf'M2C_FIELD\(\s*&\s*(?P<src>{_ID})\s*,\s*{_WORD}\s*\*\s*,\s*(?P<soff>{_NUM})\s*\)\s*;[ \t]*\n')


def _target(m):
    """(what the destination is an offset from, the offset) for one store."""
    if m['sym']:
        return 'globals', int(m['sym'][2:], 16)
    return m['base'], int(m['off'], 0)


def _runs(clean, source, opening, end):
    stores = [m for m in _STORE.finditer(clean, opening, end)]
    runs, k = [], 0
    while k < len(stores):
        first = stores[k]
        base, off = _target(first)
        run = [first]
        for later in stores[k + 1:]:
            n = len(run)
            if (later.start() != run[-1].end() or later['src'] != first['src'] or _target(later) != (base, off + 4 * n)
                    or int(later['soff'], 0) != int(first['soff'], 0) + 4 * n):
                break
            run.append(later)
        if 2 <= len(run) <= 16:
            runs.append(run)
        k += len(run)
    return runs


def _line(source, run, constant):
    first = run[0]
    record = f'__repair_block{len(run)}'
    soff = int(first['soff'], 0)
    src = f'&{first["src"]}' if not soff else f'((char *) &{first["src"]} + 0x{soff:X})'
    if first['sym']:
        symbol = first['sym']
        dst = f'0x{symbol[2:]}' if constant else f'&{symbol}'
    else:
        base = source[first.start('base'):first.end('base')]
        off = int(first['off'], 0)
        dst = base if not off else f'((char *) {base} + 0x{off:X})'
    return f'{first["indent"]}*({record} *) {dst} = *({record} *) {src};\n'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    runs = _runs(clean, source, opening, end)
    if not runs:
        return []
    result = []
    named = any(run[0]['sym'] for run in runs)
    for constant in ([True, False] if named else [False]):
        text = source
        for run in reversed(runs):
            text = text[:run[0].start()] + _line(source, run, constant) + text[run[-1].end():]
        typedefs = ''.join(f'typedef struct {{ s32 w[{n}]; }} __repair_block{n};\n'
                           for n in sorted({len(run) for run in runs})
                           if f'__repair_block{n};' not in source)
        at = source.rfind('\n', 0, span[0]) + 1
        result.append((FAMILY, text[:at] + typedefs + text[at:]))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
