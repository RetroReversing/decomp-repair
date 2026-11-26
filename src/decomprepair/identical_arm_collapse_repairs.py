"""An `if (c) { S } else { S }` whose two arms are the same statements, written once.

m2c turns a selection between two equal values into a branch (`temp ? x : x`), and an earlier repair or a reader of
the target can leave one standing, often on a pointer the draft never assigned (the condition then reads an
uninitialised local, which is wrong C and costs the pseudo a long live range from the function's entry). The
compiler folds the equal arms but keeps the condition's pseudo alive: on a 180-instruction N64 function
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) removing the dead `if (temp)` took 25 to 15, and it was what let two
pointer locals be merged (15 -> 0). Only arms made of plain statements (no braces inside) that read the same after
the whitespace is normalised, and a condition without a call, an assignment or an increment, are collapsed. The
statements stay where the `if` was (inside braces of their own when the `if` was the body of an `else`, which kept only the
first of them before). A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import edit, view

FAMILIES = ('identical_arm_collapse',)
LIMIT = 8
ARMS = re.compile(r'(?P<head>\bif\s*\((?P<cond>[^;{}]*)\)\s*)\{(?P<a>[^{}]*)\}\s*else\s*\{(?P<b>[^{}]*)\}')


def variants(source, name, header='', depth=True):
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
        text = ('\n' + indent).join(lines)
        before = part.clean[:m.start()].rstrip()
        if len(lines) > 1 and (before.endswith('else') or before.endswith(')')):
            # the `if` is the unbraced body of an `else` or another statement: the arm's statements need their braces
            text = '{\n' + indent + '  ' + ('\n' + indent + '  ').join(lines) + '\n' + indent + '}'
        out.append(edit(source, [(m.start(), m.end(), text)]))
    found = [(FAMILIES[0], c) for c in out[:LIMIT] if c != source]
    if depth and found:
        # nested: an if whose arms hold ifs that collapse (`if (a) { if (b) { g(); } else { g(); } } else { if (b) ... }`):
        # every collapse in turn, innermost first, as one child, since each step alone leaves the outer arms unequal
        # (an N64 argument-block builder had four equal calls under two conditions)
        text, steps = source, 0
        while steps < 12:
            step = variants(text, name, header, depth=False)
            if not step:
                break
            text, steps = step[0][1], steps + 1
        if steps > 1 and all(text != c for _, c in found):
            found.append((FAMILIES[0], text))
    return found
