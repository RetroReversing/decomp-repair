"""A 64-bit global multiplied and divided, which m2c writes as two 32-bit halves and a runtime call.

`clock = clock * 3 / 4ULL;` on a 64-bit global compiles, on 32-bit MIPS, to an inline shift-and-add multiply of the two
halves followed by a call to the divide helper (`__udivdi3(hi, lo, 0, 4)`). m2c has no 64-bit type here:

    temp_a1 = D_lo * 3;
    temp_ret = func_X(((D_hi * 2) | ((u32) D_lo >> 0x1F)) + D_hi + (temp_a1 < (u32) D_lo), temp_a1, 0, 4);
    D_hi = temp_ret;
    D_lo = (u32) (u64) temp_ret;

(or with the low product assigned inside the first argument). An SDK boot routine's clock-rate rescale (N64, KMC GCC
2.7.2) drafted so, and the one expression gave the target's inline multiply and call.

The children write `H = H * M / Kull;` (and `%`, the helper's name does not say which): once with the global's
declaration retyped to `unsigned long long` and the low half's removed (the target's addressing; only when nothing else
names the low half), once through a `*(unsigned long long *)&H` cast. A candidate only: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'u64_pair_libcall'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
_CALL = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<r>{_ID})\s*=\s*(?P<f>{_ID})\((?P<args>[^;{{}}]*),\s*0\s*,\s*(?P<k>{_NUM})\s*\)\s*;[ \t]*\n'
    rf'[ \t]*(?P<hi>{_ID})\s*=\s*(?P=r)\s*;[ \t]*\n'
    rf'[ \t]*(?P<lo>{_ID})\s*=\s*(?:\(\s*u32\s*\)\s*)?\(\s*u64\s*\)\s*(?P=r)\s*;[ \t]*\n')


def _split(args):
    depth = 0
    for at in range(len(args) - 1, -1, -1):
        depth += {')': 1, '(': -1}.get(args[at], 0)
        if args[at] == ',' and not depth:
            return args[:at].strip(), args[at + 1:].strip()
    return None


def _drop_declaration(text, local):
    """`text` without the declaration of a local nothing else names."""
    if len(re.findall(rf'\b{local}\b', _blank(text))) != 1:
        return text
    return re.sub(rf'(?m)^[ \t]*(?:s32|u32|int|s64|u64)\s+{local}\s*;[ \t]*\n', '', text, count=1)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    call = _CALL.search(clean, opening, end)
    if not call:
        return []
    parts = _split(call['args'])
    if not parts:
        return []
    high, low = parts
    hi, lo = call['hi'], call['lo']
    start, temp = call.start(), None
    product = rf'(?:\(\s*u32\s*\)\s*)?{lo}\s*\*\s*(?P<m>{_NUM})'
    found = re.fullmatch(product, low)
    if not found and re.fullmatch(_ID, low):
        temp = low
        found = re.search(rf'\(\s*{temp}\s*=\s*{product}\s*\)', high)
        if not found:
            line = re.compile(rf'(?m)^[ \t]*{temp}\s*=\s*{product}\s*;[ \t]*\n')
            for hit in line.finditer(clean, opening, call.start()):
                if hit.end() == call.start():
                    found, start = hit, hit.start()
    if not found or not re.search(rf'\b{hi}\b', high) or not re.search(rf'\b{lo}\b', high):
        return []
    multiplier = found['m']
    rest = clean[opening:start] + clean[call.end():end]
    # the result and the low product may be named only by their declarations once the run is gone
    if any(len(re.findall(rf'\b{local}\b', rest)) > 1 for local in filter(None, (temp, call['r']))):
        return []
    result = []
    declared = re.compile(rf'(?m)^extern\s+(?:s32|u32|int|M2C_UNK)\s+{hi}\s*;')
    low_declared = re.compile(rf'(?m)^extern\s+(?:s32|u32|int|M2C_UNK)\s+{lo}\s*;[ \t]*\n')
    spellings = []
    if declared.search(clean) and not re.search(rf'\b{lo}\b', rest):
        spellings.append(('retype', hi))
    spellings.append(('cast', f'*(unsigned long long *) &{hi}'))
    for how, value in spellings:
        for op in ('/', '%'):
            line = f'{call["indent"]}{value} = {value} * {multiplier} {op} {int(call["k"], 0)}ULL;\n'
            text = source[:start] + line + source[call.end():]
            for local in filter(None, (temp, call['r'])):
                text = _drop_declaration(text, local)
            if how == 'retype':
                text = declared.sub(f'extern unsigned long long {hi};', text, count=1)
                text = low_declared.sub('', text, count=1)
            result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
