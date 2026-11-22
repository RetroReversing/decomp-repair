"""An `if (c) { S } else { S }` whose two arms are the same statements, written once.

m2c turns a selection between two equal values into a branch (`temp ? x : x`), and an earlier repair or a reader of
the target can leave one standing, often on a pointer the draft never assigned (the condition then reads an
uninitialised local, which is wrong C and costs the pseudo a long live range from the function's entry). The
compiler folds the equal arms but keeps the condition's pseudo alive: on a 180-instruction N64 function
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) removing the dead `if (temp)` took 25 to 15, and it was what let two
pointer locals be merged (15 -> 0). Only arms made of plain statements (no braces inside) that read the same after
the whitespace is normalised, and a condition without a call, an assignment or an increment, are collapsed. The
statements stay where the `if` was. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import edit, view

FAMILIES = ('identical_arm_collapse',)
LIMIT = 8
ARMS = re.compile(r'(?P<head>\bif\s*\((?P<cond>[^;{}]*)\)\s*)\{(?P<a>[^{}]*)\}\s*else\s*\{(?P<b>[^{}]*)\}')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    out = []
    for m in ARMS.finditer(part.clean, part.opening, part.end):
        cond = m['cond']
        if re.search(r'[A-Za-z_]\w*\s*\(|(?<![=!<>])=(?!=)|\+\+|--', re.sub(r'\(\s*(?:u|s)(?:8|16|32)\s*\)\s*', '', cond)):
            continue
        a, b = (' '.join(m[k].split()) for k in ('a', 'b'))
        if not a or a != b:
            continue
        body = source[m.start('a'):m.end('a')]
        indent = re.match(r'[ \t]*', part.clean[part.clean.rfind('\n', 0, m.start())+1:m.start()])[0]
        lines = [line.strip() for line in body.strip().split('\n') if line.strip()]
        out.append(edit(source, [(m.start(), m.end(), ('\n' + indent).join(lines))]))
    return [(FAMILIES[0], c) for c in out[:LIMIT] if c != source]
