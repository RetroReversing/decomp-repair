"""A scalar global read as a loop's bound right after an array store: the global as a one-member record.

    extern s32 n;                                  typedef struct { s32 n; } n_record;  extern n_record n;
    ...                                            ...
    rows[0][i] = q;                                rows[0][i] = q;
    do { } while (0);                      ->      for (k = 0; k < n.n; k++) { ... rows[k + 1][i] = q; }
    for (k = 0; k < n; k++) { ... }

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`). sched.c orders two memory references only when `true_dependence`
says they may alias, and it says no for an array element store (`MEM_IN_STRUCT_P`, varying address) against a
scalar global load (fixed address, not in a struct): the first scheduler sinks the store below the bound's load,
into the loop test's delay slot. An empty `do { } while (0)` between them fixes the store's place (a loop note is a
scheduling barrier) but also keeps everything before it there, and the loop's hoisted base address (`la`, set before
the note because cse2 shares it with the store's symbol) can then no longer fill the load's delay slot after the
bound's `lw`, where the target has it. Read through a record, the bound is a `MEM_IN_STRUCT_P` load, the store and
the load are ordered by their dependence alone, and the note can go: on a 534-instruction menu builder this was the
last step (120 -> 0, four reordered rows; the same with the bound as `n[0]` of an array).

Children, for a `for` loop whose condition compares the counter with a scalar global that the source itself
declares `extern T G;` (an integer type) and reads nowhere else as an lvalue: the global as a one-member record
(typedef'd beside the declaration) with every read of it in the function as `G.n`, with the empty `do { } while
(0);` statements directly before the loop removed (one child) and kept (a second), and the same with `G[0]` of an
array. The judge decides every child.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'loop_bound_record_read'
FAMILIES = (FAMILY,)
_TYPE = r'(?:s32|u32|s16|u16|s8|u8|int|unsigned\s+int|unsigned|short|unsigned\s+short|long)'
_FENCE = re.compile(r'(?:\s*do\s*\{\s*\}\s*while\s*\(\s*0\s*\)\s*;)+\s*$')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    seen = set()
    for loop in re.finditer(rf'\bfor\s*\([^;]*;\s*{IDENT}\s*(?:<|<=|!=)\s*(?P<g>{IDENT})\s*;', clean[:part.end]):
        if loop.start() < part.opening:
            continue
        glob = loop['g']
        if glob in seen:
            continue
        seen.add(glob)
        decl = re.search(rf'(?m)^[ \t]*extern\s+(?P<t>{_TYPE})\s+{re.escape(glob)}\s*;[^\n]*\n', clean[:part.opening])
        if not decl:
            continue
        body = clean[part.opening:part.end]
        if re.search(rf'(?<![\w.>]){re.escape(glob)}\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=|\[)|&\s*{re.escape(glob)}\b'
                     rf'|(?:\+\+|--)\s*{re.escape(glob)}\b', body):
            continue
        uses = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(glob)}\b', clean[part.opening:part.end])]
        fence = _FENCE.search(clean[part.opening:loop.start()])
        for record in (True, False):
            if record:
                head = f'typedef struct {{ {decl["t"]} n; }} {glob}_record;\nextern {glob}_record {glob};\n'
                read = f'{glob}.n'
            else:
                head = f'extern {decl["t"]} {glob}[];\n'
                read = f'{glob}[0]'
            for drop in ([True, False] if fence else [False]):
                text, last = [], 0
                cuts = [(part.opening + u, part.opening + u + len(glob), read) for u in uses]
                if drop:
                    indent = re.search(r'([ \t]*)$', source[:loop.start()]).group(1)
                    cuts.append((part.opening + fence.start(), part.opening + fence.end(), '\n' + indent))
                cuts.append((decl.start(), decl.end(), None))
                for start, stop, new in sorted(cuts):
                    text.append(source[last:start])
                    text.append(head if new is None else new)
                    last = stop
                text.append(source[last:])
                out.append(''.join(text))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
