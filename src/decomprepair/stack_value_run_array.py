"""Neighbouring stack locals the target keeps in memory, declared as the one array they were.

m2c names each stack slot it saw as a local of its own:

    u8 sp88;  u8 sp89;                           u8 sp88[2];
    sp88 = 1;  sp89 = 0;                    ->   sp88[0] = 1;  sp88[1] = 0;
    g(a, (s32) sp88);  g(b, (s32) sp89);         g(a, (s32) sp88[0]);  g(b, (s32) sp88[1]);

As scalars whose address is never taken, gcc keeps them in registers (or propagates the constants), while the target
stores each with `sb ..., 0x88($sp)` and loads it back at each use: it is an array. `stack_run_array_repairs` needs the
first element's address to escape; this needs none. The evidence is the target storing every slot of the run at its own
`$sp` offset with the type's width. One child with every run. On a 461-instruction N64 menu screen (SN64 GCC 2.8.1) two
highlight bytes as scalars scored 9551 against 6395.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'stack_value_run_array'
FAMILIES = (FAMILY,)
SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4}
STORES = {'sb': 1, 'sh': 2, 'sw': 4, 'swc1': 4}
DECL = re.compile(r'(?m)^[ \t]*(?P<type>[su](?:8|16|32)|f32)[ \t]+sp(?P<slot>[0-9A-F]+);(?:[ \t]*/\*[^\n]*\*/)?[ \t]*\n')


def stored(asm):
    """{(offset from $sp, width)} the target stores."""
    return {(int(hit[2], 0), STORES[hit[1]])
            for hit in re.finditer(r'\b(sb|sh|sw|swc1)\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)', asm)}


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or not asm:
        return []
    clean, low, high = part.clean, part.opening, part.end
    seen = stored(asm)
    declared = sorted((int(hit['slot'], 16), hit['type'], hit) for hit in DECL.finditer(clean, low, high))
    body = clean[low:high]

    def plain(slot, kind):
        local = f'sp{slot:X}'
        return ((slot, SIZES[kind]) in seen and not re.search(rf'&\s*{local}\b', body)
                and not re.search(rf'(?<![\w.>]){local}\s*(?:\[|\.|->)', body))

    runs, k = [], 0
    while k < len(declared):
        slot, kind, _ = declared[k]
        run = [declared[k]]
        while (k + len(run) < len(declared) and declared[k + len(run)][0] == slot + len(run) * SIZES[kind]
               and declared[k + len(run)][1] == kind):
            run.append(declared[k + len(run)])
        if len(run) > 1 and all(plain(entry[0], entry[1]) for entry in run):
            runs.append(run)
        k += len(run)
    if not runs:
        return []
    edits = []
    for run in runs:
        first = run[0]
        array = f'sp{first[0]:X}'
        for index, (slot, kind, declaration) in enumerate(run):
            local = f'sp{slot:X}'
            line = source[declaration.start():declaration.end()]
            indent = line[:len(line) - len(line.lstrip(' \t'))]
            edits.append((declaration.start(), declaration.end(),
                          f'{indent}{kind} {array}[{len(run)}];\n' if not index else ''))
            for use in re.finditer(rf'(?<![\w.>]){local}(?!\w)', body):
                at = low + use.start()
                if not declaration.start() <= at < declaration.end():
                    edits.append((at, low + use.end(), f'{array}[{index}]'))
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
