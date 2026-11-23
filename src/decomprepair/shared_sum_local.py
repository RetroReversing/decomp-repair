"""One local for a sum a block computes three times, set once before its first use.

m2c repeats a small sum wherever the game used it:

    p->y = y0 + 1;  q->y = dy + (y0 + 1);  r->y = y0 + 1;

gcc 2.7.2's cse shares the three adds only when the second and third meet the first in one expression chain; when the
sum feeds `dy + (y0 + 1)` it reassociates that to `(dy + 1) + y0`, and the add the target has once (`addiu $a1, $s2, 1`,
read three times) is computed twice more. Naming the sum (`yy = y0 + 1;` before the first use) keeps the target's single
`addiu` and its `addu` of the other operand (a 795-instruction N64 object spawner: 4325 -> 4030, the reassociated adds
gone). The reading of cse.c is a hypothesis; the judge decides.

The shape: `local + literal` written three or more times in the top-level statements of one block, each time as a whole
right-hand side (`x = local + 1;`) or in parentheses, `local` a plain integer local that is not assigned between the first
and the last of them (nor address-taken). One child per sum declares `<local>_sum` with the local's type at the head of the
function, assigns it just before the first statement that uses it, and replaces every use.
"""
import re

from .arm_block_support import IDENT, NUMBER, brace_pairs, local_declaration, statements
from .integer_repair_support import edit, view

FAMILY = 'shared_sum_local'
FAMILIES = (FAMILY,)

SUM = re.compile(rf'(?P<open>\(\s*)?(?<![\w.>\]])(?P<var>{IDENT})\s*\+\s*(?P<number>{NUMBER})(?![\w.])(?P<close>\s*\))?')


def _sites(text, base):
    """(start, end, var, number) of each qualifying use in `text`: parenthesised, or a whole assignment value."""
    found = []
    for hit in SUM.finditer(text):
        before = text[:hit.start()].rstrip()
        after = text[hit.end():].lstrip()
        if hit['open'] and hit['close']:
            found.append((base + hit.start(), base + hit.end(), hit['var'], hit['number']))
        elif not hit['open'] and not hit['close'] and re.search(r'[^=!<>+\-*/|&^]=$', before) and after.startswith(';'):
            found.append((base + hit.start(), base + hit.end(), hit['var'], hit['number']))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    out = []
    for block_open, block_close in sorted(pairs.items()):
        units = statements(clean, block_open + 1, block_close)
        uses = {}
        for index, (start, end) in enumerate(units):
            text = clean[start:end]
            if '{' in text:
                continue
            for a, b, var, number in _sites(text, start):
                uses.setdefault((var, number), []).append((index, a, b))
        for (var, number), sites in uses.items():
            if len(sites) < 3:
                continue
            declared = local_declaration(clean, part.opening, var)
            if not declared or declared[1] or declared[0] in ('f32', 'f64', 'float', 'double'):
                continue
            first, last = sites[0][0], sites[-1][0]
            span = ' '.join(clean[units[i][0]:units[i][1]] for i in range(first, last + 1))
            if re.search(rf'&\s*{re.escape(var)}\b', clean[part.opening:part.end]):
                continue
            if re.search(rf'(?<![\w.>]){re.escape(var)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(var)}\b|{re.escape(var)}\s*(?:\+\+|--)', span):
                continue
            fresh = f'{var}_sum'
            if re.search(rf'\b{fresh}\b', clean):
                continue
            edits = [(a, b, fresh) for _, a, b in sites]
            at = units[first][0]
            line = source.rfind('\n', 0, at) + 1
            indent = re.match(r'[ \t]*', source[line:])[0]
            edits.append((line, line, f'{indent}{fresh} = {var} + {number};\n'))
            nl = clean.find('\n', part.opening) + 1
            body_indent = re.match(r'[ \t]*', source[nl:])[0] or '  '
            edits.append((nl, nl, f'{body_indent}{declared[0]} {fresh};\n'))
            text = edit(source, edits)
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)
