"""A run of word loads into temporaries and the run of stores that writes them back, as the struct assignment it was.

A record copied with `*dst = *src` (or `a->x[i] = a->y[i]` of a three-word record) comes back from a decompiler, or from
an earlier search, as one temporary per word:

    v0 = *(s32 *)(p + 0xDA4);
    v1 = *(s32 *)(p + 0xDA8);
    v2 = *(s32 *)(p + 0xDAC);
    *(s32 *)(p + 0x75C) = v0;
    *(s32 *)(p + 0x760) = v1;
    *(s32 *)(p + 0x764) = v2;

The instructions are the same `lw; lw; lw; sw; sw; sw`, but gcc 2.7.2 expands a block move (`movstrsi`) with its own
scratch registers, one more than the words it copies, so the registers around it differ: in a KMC GCC 2.7.2 `-O1`
loop copying 96 three-word records (an N64 game) the loop counter took `$a2` with the temporaries and `$a3` with the
struct assignment, as the target has (25 -> 0; a `volatile` an earlier search had put on the last store, which only
stood in for that, went with it). A hypothesis like every family's; the judge decides.

`word_block_copy` reads m2c's direct `M2C_FIELD(d, s32 *, k) = M2C_FIELD(s, s32 *, k)` stores; this one reads the
temporaries. Each temporary must be read only by its store. Children (`word_temp_block_copy`): each run alone, then all
of them in one child.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'word_temp_block_copy'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
WORD = r'(?:volatile\s+)?(?:s32|u32|int|M2C_UNK|M2C_UNK32)'
# a word through a base identifier and a constant offset: `*(s32 *)(p + 0x10)`, `*(volatile s32 *)(p + 4)`,
# `M2C_FIELD(p, s32 *, 0x10)`, `*(s32 *)p` (offset 0)
ACCESS = (r'(?:\*\s*\(\s*' + WORD + r'\s*\*\s*\)\s*(?:\(\s*(?P<{0}b>' + IDENT + r')\s*\+\s*(?P<{0}o>' + NUM + r')\s*\)'
          r'|(?P<{0}z>' + IDENT + r'))'
          r'|M2C_FIELD\(\s*(?P<{0}f>' + IDENT + r')\s*,\s*' + WORD + r'\s*\*\s*,\s*(?P<{0}fo>' + NUM + r')\s*\))')
LOAD = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<t>' + IDENT + r')\s*=\s*(?:\(\s*s32\s*\)\s*)?' + ACCESS.format('s')
                  + r'\s*;[ \t]*\n')
STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)' + ACCESS.format('d') + r'\s*=\s*(?:\(\s*s32\s*\)\s*)?(?P<t>' + IDENT
                   + r')\s*;[ \t]*\n')


def _address(m, side):
    """(base, offset) of a LOAD or STORE match's access."""
    if m[side + 'b']:
        return m[side + 'b'], int(m[side + 'o'], 0)
    if m[side + 'z']:
        return m[side + 'z'], 0
    return m[side + 'f'], int(m[side + 'fo'], 0)


def _runs(clean, opening, end):
    """[(start, stop, n, dst, dbase, src, sbase, temps)] for each load run directly followed by its store run."""
    out = []
    pos = opening + 1
    while (first := LOAD.search(clean, pos, end)) is not None:
        loads, cursor = [first], first.end()
        while (nxt := LOAD.match(clean, cursor)) is not None and nxt['indent'] == first['indent']:
            loads.append(nxt)
            cursor = nxt.end()
        stores = []
        while (nxt := STORE.match(clean, cursor)) is not None and nxt['indent'] == first['indent']:
            stores.append(nxt)
            cursor = nxt.end()
        pos = loads[-1].end()
        n = len(loads)
        if n < 2 or len(stores) < n:
            continue
        src, sbase = _address(loads[0], 's')
        dst, dbase = _address(stores[0], 'd')
        temps = [m['t'] for m in loads]
        if len(set(temps)) != n or src in temps or dst in temps:
            continue
        if any(_address(m, 's') != (src, sbase + 4 * k) for k, m in enumerate(loads)):
            continue
        if any(m['t'] != temps[k] or _address(m, 'd') != (dst, dbase + 4 * k) for k, m in enumerate(stores[:n])):
            continue
        out.append((first.start(), stores[n - 1].end(), n, dst, dbase, src, sbase, temps))
        pos = stores[n - 1].end()
    return out


def _used_once(clean, opening, end, temp, start, stop):
    """The temporary is named in the body only inside the run (its load and its store) and in declarations."""
    for m in re.finditer(r'\b' + re.escape(temp) + r'\b', clean[opening:end]):
        at = opening + m.start()
        if start <= at < stop:
            continue
        line = clean[clean.rfind('\n', 0, at) + 1:clean.find('\n', at)]
        if not re.match(r'\s*(?:register\s+)?(?:volatile\s+)?(?:s32|u32|int|M2C_UNK|M2C_UNK32)\b[^=;()]*;\s*$', line):
            return False
    return True


def _rewrite(source, span, runs):
    text = source
    records = set()
    for start, stop, n, dst, dbase, src, sbase, temps in sorted(runs, reverse=True):
        indent = re.match(r'[ \t]*', text[start:]).group()
        record = f'__repair_words{n}'
        records.add(n)
        line = (f'{indent}*({record} *) ((s8 *) {dst} + 0x{dbase:X}) = '
                f'*({record} *) ((s8 *) {src} + 0x{sbase:X});\n')
        text = text[:start] + line + text[stop:]
    at = source.rfind('\n', 0, span[0]) + 1
    typedefs = ''.join(f'typedef struct {{ s32 w[{n}]; }} __repair_words{n};\n' for n in sorted(records)
                       if f'}} __repair_words{n};' not in text)
    return text[:at] + typedefs + text[at:]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    runs = [r for r in _runs(clean, opening, end)
            if all(_used_once(clean, opening, end, t, r[0], r[1]) for t in r[7])]
    if not runs:
        return []
    result = [(FAMILY, _rewrite(source, span, [r])) for r in runs[:4]]
    if len(runs) > 1:
        result.append((FAMILY, _rewrite(source, span, runs)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
