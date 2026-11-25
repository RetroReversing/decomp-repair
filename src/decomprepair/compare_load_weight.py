"""A global compared with a constant (`if (D_X == 1)`) read into a local in a one-shot scope two or three deep, so its
load outranks the constant in local-alloc and takes the address's register.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2 -mfp32`), a 182-instruction N64 state machine at 15: the only rows were
`lui $v0, %hi(D_X); lw $v0, %lo(D_X)($v0); li $v1, 1; bne $v0, $v1` where ours had the load in `$v1` and the
constant in `$v0`. Read in local-alloc.c (2.8.1) and the `-dl` dump: the block after the call holds exactly three
local quantities (the `lui`, the `lw`, the `li`), and a block of three is ordered by a fixed exchange over
`qty_compare(0, 1)` and `qty_compare(1, 2)` (it compares quantity numbers, not positions). Each quantity's priority is
`floor_log2(refs) * refs / (death - birth)`: the constant, set one insn before the branch, beats the load (two refs over
a longer life), is allocated before it and takes `$v0`, which the dying `lui` frees; the load then lands in `$v1`.
flow.c counts a reference once more per enclosing loop, and `do { } while (0)` is a loop at no code cost: the load
written `do { do { v = D_X; } while (0); } while (0); if (v == 1)` has refs 4 (priority 2 against the constant's 1),
the exchange keeps birth order, and the load takes the `lui`'s `$v0`, the constant `$v1`: 15 -> 0 (one deep: 15).
The scopes are scaffolding; polishing removes them once the match is recorded.

Offered for an `if` statement (not an `else if`) whose condition is `G == K` or `G != K` with `G` a plain identifier
that is not a local or parameter and `K` an integer literal: depths 2, 1 and 3.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compare_load_weight'
FAMILIES = (FAMILY,)
LIMIT = 6
DEPTHS = (2, 1, 3)

_IDENT = r'[A-Za-z_]\w*'
_INT = r'-?(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'


def _fresh(clean, base='mode'):
    name, n = base, 2
    while re.search(r'\b' + name + r'\b', clean):
        name, n = f'{base}{n}', n + 1
    return name


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
    header = clean[span[0]:opening]
    results = []
    for m in re.finditer(r'(?<=[;{}])(\s*)if\s*\(\s*(' + _IDENT + r')\s*([!=]=)\s*(' + _INT + r')\s*\)', body):
        glob = m[2]
        if re.search(r'\b' + glob + r'\b', header) or re.search(
                r'(?:^|(?<=[;{}(,]))\s*(?:(?:const|unsigned|signed|struct|volatile)\s+)*' + _IDENT + r'[\s*]+' + glob
                + r'\s*(?:[;=,\[)])', body):
            continue  # a parameter or a local: no load to weigh
        if not re.search(r'\bextern\b[^;]*\b' + glob + r'\b', clean[:span[0]]) and not re.search(
                r'^[^\n(]*\b' + glob + r'\s*(?:;|=|\[)', clean[:span[0]], re.M):
            continue  # not a global this file declares
        start = opening + m.start() + len(m[1])
        cond_open = opening + m.start() + m[0].index('(')
        cond_close = close(clean, cond_open)
        line = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        local = _fresh(clean)
        for depth in DEPTHS:
            load = 'do { ' * depth + f'{local} = {glob};' + ' } while (0);' * depth
            text = (source[:start] + load + '\n' + indent + f'if ({local} {m[3]} {m[4]})' + source[cond_close:])
            text = text[:opening + 1] + f'\n    __typeof__({glob}) {local};' + text[opening + 1:]
            results.append((FAMILY, text))
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
