"""A loop variable that is also a call's argument gets its own local, so it stops preferring the argument register.

`while ((v = *p++) != K) call(v, t);` copies `v` straight into the first argument register, and KMC GCC 2.7.2's global
allocator records that copy as a preference for `$a0` on the *pseudo*, which is the same pseudo m2c reused for every
other loop's key (`v = *key` ... `(u16)v` compared in a nested search). The shared variable therefore sat in `$a0` in four
unrelated search loops where the target keeps it in `$v1` and the loops' `-1` constant in `$a0`. Giving the argument
loop a variable of its own removed the preference from the others: 180 -> 20 on a 219-instruction N64 function (`-G0
-mips3 -mgp32 -mfp32 -O2`; with `loop_exit_value_block`, 285 -> 20 together). Read from the allocator's preference
table (`-dg`, "82 preferences: 4"), a hypothesis for other compilers.

`variants` offers, for a scalar local read or assigned in at least one other statement, each `while ((V = E) != K)`
loop whose body is plain statements passing `V` as a direct call argument, with a new local `V_arg` of V's type
standing in for V in that loop (its condition and body). The judge decides.
"""
import re

from .integer_repair_support import DECL, IDENT, edit, view

FAMILY = 'argument_loop_split'
FAMILIES = (FAMILY,)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    clean, found = part.clean, []
    for decl in DECL.finditer(clean, part.opening + 1, part.end):
        variable, split = decl['name'], decl['name'] + '_arg'
        if split in clean:
            continue
        loops = re.compile(rf'while\s*\(\s*\(\s*{re.escape(variable)}\s*=[^{{}};]*\)[^{{}};]*\)\s*{{(?P<body>[^{{}}]*)}}')
        argument = re.compile(rf'\b{IDENT}\s*\((?:[^;(),]*,)*\s*{re.escape(variable)}\s*[,)]')
        edits = []
        for hit in loops.finditer(clean, part.opening + 1, part.end):
            outside = len(re.findall(rf'(?<![\w.>]){re.escape(variable)}\b', clean[part.opening:part.end])) - \
                len(re.findall(rf'(?<![\w.>]){re.escape(variable)}\b', hit[0]))
            if not argument.search(hit['body']) or outside < 2:
                continue
            text = re.sub(rf'(?<![\w.>]){re.escape(variable)}\b', split, source[hit.start():hit.end()])
            edits.append((hit.start(), hit.end(), text))
        if edits:
            at = source.find('\n', decl.end()) + 1
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, decl.start()) + 1:])[0]
            edits.append((at, at, f'{indent}{decl["type"]} {split};\n'))
            found.append((FAMILY, edit(source, edits)))
    return found
