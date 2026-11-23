"""A store written after a call that the target does before it, in an arm that calls the same function as others.

m2c writes an arm as `call(...);` then the store the arm also makes (`*(T *)(p + 0xA4) = 0;`), the order the arms
read in. When the original stored first and called last, the arms end in the same `jal` and the final jump pass
(`jump.c`, cross-jumping) merges them into one shared call (`j tail` with the arm's argument in the delay slot); with
the store after the call the arms' tails differ and nothing merges, so the call stays in every arm. A 970-instruction
N64 state-machine handler (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) had `func_80117EC8(arg0, 1); *(s32 *)(p +
0xA4) = 0;` in one arm of a switch whose other arms ended in the same call: swapping the pair was 6335 -> 6155 alone,
and it is what lets `call_into_each_arm` reach the target's shared tail (6155 -> 4310 with it; the chain without the
swap stopped at 5030).

A statement-level call whose callee is called at two or more places, followed by a plain memory store with no call in
it, swapped. Only the nearest pairs are offered. A candidate rewrite: the exact judge decides whether the call
may move past the store.
"""
import re

from .integer_repair_support import view
from .line_scan import apply, lines

FAMILY = 'call_store_swap'
FAMILIES = (FAMILY,)
LIMIT = 8

CALL = re.compile(r'(?P<callee>[A-Za-z_]\w*)\s*\(.*\)\s*;')
STORE = re.compile(r'(?:\*\s*\(.*\)|[A-Za-z_]\w*(?:\s*\[[^\]]*\]|\s*->\s*\w+|\s*\.\s*\w+)+)\s*=(?!=)[^;]*;')
TYPES = frozenset('''s8 u8 s16 u16 s32 u32 s64 u64 f32 f64 void char short int long unsigned signed float double
volatile const struct union M2C_FIELD'''.split())


def _calls(text):
    return [m['name'] for m in re.finditer(r'(?P<name>[A-Za-z_]\w*)\s*\(', text) if m['name'] not in TYPES]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    callee = {}
    for index, line in enumerate(body):
        m = CALL.fullmatch(line.stripped)
        if m and m['callee'] not in TYPES and m['callee'] not in {'if', 'while', 'for', 'switch', 'return'}:
            callee.setdefault(m['callee'], []).append(index)
    found = []
    for sites in callee.values():
        if len(sites) < 2:
            continue
        for index in sites:
            if index + 1 >= len(body):
                continue
            first, second = body[index], body[index + 1]
            if first.indent != second.indent or not STORE.fullmatch(second.stripped) or _calls(second.stripped):
                continue
            found.append((index, first, second))
    out = []
    for _, first, second in sorted(found, key=lambda item: item[0]):
        child = apply(source, [(first.start, second.end, f'{second.source}\n{first.source}\n')])
        if child != source and child not in out:
            out.append(child)
        if len(out) >= LIMIT:
            break
    return [(FAMILY, child) for child in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
