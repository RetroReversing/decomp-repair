"""A shared `return K;` moved from the end of the function to the first place that jumps to it.

m2c writes a constant return reached from several arms as a label at the function's end:

    if (a != b) { BODY ...; goto L; }        if (a == b) { L: return K; }
    goto L;                           ->     BODY ...; goto L;
    ...                                      ...
    L: return K;                             goto L;

The compiler lays the block where the source has it. On an N64 interpolation (GCC 2.7.2 `-O1`) the target held the
constant return right after the first arm's compare, with the later arms jumping back to it; from the machine draft the
library stopped at 2050, from this layout it reached 70, and with `param_difference_reuse` 0.

shared_return_hoist
    `if (C) { B... goto L; } goto L;` (no `else`) where `L:` labels one `return V;` (V a literal) that ends the
    function. Child: `if (!C) { L: return V; } B... goto L;` and `goto L;` where the label stood. At most 8.
"""
import re

from .arm_block_support import brace_pairs, statements
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'shared_return_hoist'
FAMILIES = (FAMILY,)
LIMIT = 8
LABELLED = re.compile(rf'(?P<label>{IDENT})\s*:\s*return\s+(?P<v>-?[0-9.][\w.]*)\s*;\s*\}}\s*$')
IF = re.compile(r'\bif\s*\(')


def _negated(text):
    text = text.strip()
    plain = re.fullmatch(r'([\w.\->\[\]]+)\s*(==|!=)\s*([\w.\->\[\]]+)', text)
    if plain:
        return f"{plain[1]} {'==' if plain[2] == '!=' else '!='} {plain[3]}"
    return f'!({text})'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    end = LABELLED.search(clean[:part.end])
    if not end or end.start() < part.opening:
        return []
    label, value = end['label'], end['v']
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    jump = re.compile(rf'goto\s+{label}\s*;')
    value = source[end.start('v'):end.end('v')]
    out = []
    for hit in IF.finditer(clean, part.opening, end.start()):
        paren = close(clean, hit.end() - 1, '(', ')')
        if paren is None:
            continue
        brace = re.compile(r'\s*\{').match(clean, paren)
        if not brace:
            continue
        opening = brace.end() - 1
        closing = pairs.get(opening)
        if closing is None:
            continue
        after = re.compile(rf'\s*(goto\s+{label}\s*;)').match(clean, closing + 1)
        if not after:
            continue
        inner = list(statements(clean, opening + 1, closing))
        if not inner or not jump.fullmatch(clean[inner[-1][0]:inner[-1][1]].strip()):
            continue
        line = source.rfind('\n', 0, hit.start()) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        body = source[opening + 1:closing].strip('\n').rstrip()
        body = '\n'.join(text[4:] if text.startswith(indent + '    ') else text for text in body.split('\n'))
        condition = _negated(source[hit.end():paren - 1])
        new = (f'if ({condition}) {{\n{label}:\n{indent}    return {value};\n{indent}}}\n{body}')
        edits = [(hit.start(), after.end(1), new), (end.start(), end.end('v') + clean[end.end('v'):].index(';') + 1,
                                                    ('    ' if source[end.start() - 1] == '\n' else '') + f'goto {label};')]
        result = edit(source, edits)
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # registry: no wiring
