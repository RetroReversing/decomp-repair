"""A word local that one arm of an `if` passes on and the other stores as halfwords, with a `u16` copy made before the
`if` for the stores: `w = G; if (c) { f((s16) w); } else { *p = (u16) w; *q = (s16) w; }` as
`{ u16 copy; w = G; copy = w; if (c) { f((s16) w); } else { *p = copy; *q = copy; } }`.

KMC GCC 2.7.2 (`-O2`, N64) keeps a `u16` local in a halfword pseudo (MIPS defines no PROMOTE_MODE): the copy is a
`move` before the branch (`lw $a2, G; ..; move $a0, $a2`), the call arm extends the word (`sll $a2, 16; sra $a2, 16`)
and the store arm stores the copy (`sh $a0, 0x180($v0)`), which is what a sound-sequence interpreter's variable-write
command has. Written with the casts at the stores, both arms read one pseudo and the store arm's register follows the
call's argument. On that 1315-instruction function 3560 -> 3455. The reading is from the output; the judge decides.

Rewrites `W = E;` followed (at most one statement later) by an `if (..) {..} else {..}` whose `else` arm stores `W`
only as `(u16) W` or `(s16) W` and whose other arm reads `W` otherwise. Bounded to `LIMIT` children.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'halfword_store_copy'
FAMILIES = (FAMILY,)
LIMIT = 4


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    out = []
    for found in re.finditer(rf'(?m)^(?P<indent>[ \t]*)(?P<w>{IDENT})\s*=(?!=)\s*[^;{{}}]+;[ \t]*\n', clean[lo:hi]):
        start, end = lo + found.start(), lo + found.end()
        var, indent = found['w'], found['indent']
        guard = re.compile(r'(?:[ \t]*[^;{}\n]+;[ \t]*\n)?[ \t]*if\s*\(').match(clean, end)
        if not guard:
            continue
        cond_end = close(clean, guard.end() - 1)
        then = re.compile(r'\s*\{').match(clean, cond_end) if cond_end else None
        if not then:
            continue
        a = then.end() - 1
        b = close(clean, a, '{', '}')
        other = re.compile(r'\s*else\s*\{').match(clean, b) if b else None
        if not other:
            continue
        c = other.end() - 1
        d = close(clean, c, '{', '}')
        if not d:
            continue
        mention = re.compile(rf'(?<![\w.>]){re.escape(var)}\b')
        narrow = re.compile(rf'=\s*\(\s*[us]16\s*\)\s*{re.escape(var)}\s*;')
        arm = clean[c:d]
        stores = list(narrow.finditer(arm))
        if not stores or len(stores) != len(mention.findall(arm)) or not mention.search(clean[a:b]):
            continue
        if re.search(r'\bcopy\b', clean[lo:hi]):
            continue
        new_arm = source[c:d]
        new_arm = narrow.sub('= copy;', new_arm)
        text = (source[:start] + f'{indent}{{\n{indent}u16 copy;\n' + source[start:end] + f'{indent}copy = {var};\n'
                + source[end:c] + new_arm + '\n' + indent + '}' + source[d:])
        out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
