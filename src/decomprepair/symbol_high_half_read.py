"""A word global's high halfword read as the variable shifted (`G >> 16`), not through its address (`*(u16 *) &G`).

On a big-endian processor `*(u16 *) &G` and `(u32) G >> 16` are the same value. The compiler does not see them the
same way. Expanding `*(u16 *) &G` goes through `memory_address`, which puts the constant address in a pseudo first;
cse then looks up that pseudo's class and, when a pointer local holds `&G` in the same block (`u32 *cmd = &G;`) and
the symbol's address costs more than a register (KMC GCC 2.7.2 with `-G0`: `mips_address_cost` is 2 for a symbol
outside small data, 1 for a register), it rewrites the load through the pointer: `lhu $v0, 0($s0)`, with the
pointer's `lui`/`addiu` hoisted above it. The variable itself is a `MEM` of the constant address (its DECL_RTL),
which `find_best_addr` never replaces, and combine narrows `(G >> 16)` to a halfword load: `lui $v0, %hi(G);
lhu $v0, %lo(G)($v0)`, the pointer set after it, as the target has it (a sound-sequence interpreter's arm, 535 -> 165).

Children: each `*((u16 *) (&G))` (also `*((u16 *) (((char *) (&G)) + 0))` and `*((s16 *) ...)`, signed as `(s16)`)
of a word global the header or source declares, rewritten one at a time and all together. Big-endian MIPS only.
The cse rule is read from cse.c (`find_best_addr`); proposals only, the judge decides."""
import re

FAMILIES = ('symbol_high_half_read',)
FAMILY = FAMILIES[0]
LIMIT = 8

_READ = re.compile(r'\*\(\((u16|s16) \*\) \((?:\(\(char \*\) \(&(\w+)\)\) \+ 0|&(\w+))\)\)')
_WORD = ('u32', 's32', 'int', 'unsigned int', 'long', 'unsigned long')


def _word_globals(text):
    return {m[2]: m[1] for m in re.finditer(r'(?m)^extern ((?:unsigned )?\w+) (\w+);', text) if m[1] in _WORD}


def variants(source, name=None, header=None, arch=None):
    if arch not in (None, 'mips'):
        return []
    words = _word_globals((header or '') + '\n' + source)
    sites = []
    for m in _READ.finditer(source):
        sym = m[2] or m[3]
        if sym not in words:
            continue
        shifted = f'({sym} >> 16)' if words[sym].startswith('u') else f'((u32) {sym} >> 16)'
        sites.append((m.start(), m.end(), shifted if m[1] == 'u16' else f'((s16) {shifted})'))
    if not sites:
        return []

    def apply(chosen):
        text = source
        for a, b, new in sorted(chosen, reverse=True):
            text = text[:a] + new + text[b:]
        return text

    out = [apply([site]) for site in sites]
    if len(sites) > 1:
        out.append(apply(sites))
    return [(FAMILY, s) for s in out[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch'),
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
