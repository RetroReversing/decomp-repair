"""A guard's value copied into a variable of its own and the original reassigned, so cse keeps the copy.

m2c names a loaded pointer once and tests it (`temp = table[i]; ... if (temp != NULL) { use(temp); call(temp); }`). GCC
2.7.2's first cse leaves a copy `p = temp` alone (loop.c wants the pseudos as written) but its second one, after the loop
pass, replaces every later use of `p` by `temp`, so the pointer that lives across the call is the loaded value itself
and takes the saved register: `lw $s0,($v0); beqz $s0,L`. The game's code kept two registers: the load and the branch on
`$v0`, the copy into `$s0` in the branch's delay slot (`lw $v0,($v0); beqz $v0,L; move $s0,$v0`). cse stops treating the
copy as equal to the value once the value is assigned again, and the assignment is dead (the flow pass deletes it), so
the source

    if (temp != NULL) { p = temp; temp = 0; use(p); call(p); }

gives the game's pair at no instruction cost: 459 -> 244 on a 731-instruction KMC N64 function (`-G0 -mips3 -mgp32
-mfp32 -O2 -fno-strength-reduce`); a wrapper or label inside the loop instead changed the whole allocation (2200+).

Offered for `if (local != NULL) {` (or `!= 0`, or the bare local) where the local is a declared scalar or pointer that
is read at least twice in the block and nowhere after it, and every mention before the `if` is an assignment. The
block's mentions become a new local; the copy and the reassignment come first. A candidate: the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'guard_copy_cse_barrier'
FAMILIES = (FAMILY,)
LIMIT = 8
SUFFIX = '_gc'
_GUARD = re.compile(rf'\bif\s*\(\s*(?P<var>{IDENT})\s*(?:!=\s*(?:NULL|0)\s*)?\)\s*{{')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    result = []
    for hit in _GUARD.finditer(clean, part.opening, part.end):
        var = hit['var']
        if var.endswith(SUFFIX) or var + SUFFIX in clean:
            continue
        declaration = re.search(rf'(?m)^[ \t]*(?P<type>[A-Za-z_][\w ]*?)\s*(?P<star>\*?)\s*\b{var}\s*;[ \t]*$',
                                clean[part.opening:hit.start()])
        if not declaration or re.search(r'\b(?:struct|union|volatile|register)\b', declaration['type']):
            continue
        opening = hit.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        inside = clean[opening + 1:end - 1]
        if len(re.findall(rf'\b{var}\b', inside)) < 2 or re.search(rf'&\s*{var}\b|\b(?:goto|return)\b|\b{IDENT}\s*:(?!:)', inside):
            continue
        if re.search(rf'\b{var}\b', clean[end:part.end]):
            continue
        before = clean[part.opening + 1:hit.start()]
        reads = [m for m in re.finditer(rf'\b{var}\b', before)
                 if m.start() >= declaration.end() - 1
                 and not re.match(r'\s*=(?!=)', before[m.end():])]
        if reads:
            continue
        copy = var + SUFFIX
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:hit.start()])[0] + '    '
        zero = '0' if not declaration['star'] else 'NULL'
        body = re.sub(rf'\b{var}\b', copy, source[opening + 1:end - 1])
        text = edit(source, [
            (opening + 1, end - 1, f'\n{indent}{copy} = {var};\n{indent}{var} = {zero};{body}'),
            (part.opening + declaration.end(), part.opening + declaration.end(),
             f'\n    {declaration["type"].strip()} {declaration["star"]}{copy};')])
        result.append((FAMILY, text))
        if len(result) >= LIMIT:
            break
    return result
