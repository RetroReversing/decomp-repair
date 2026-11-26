"""A pointer that is only read or written below itself, given a second pointer at the lowest of those places.

The target holds the address of a global in a register and reaches the words in front of it with negative offsets
(`lui $t0; addiu $t0; ... sb $v0, -4($t0)`), while the C's `p = D_X; p[-4] = v;` compiles to `sb $v0, %lo(D_Y)($at)`:
KMC GCC 2.7.2 knows `p` is a symbol's address and folds each `p[-k]` back into an absolute access. A second pointer
set once from the first (`q = p - 4;`) and indexed forwards (`q[0]`) stays base-relative. On a KMC 2.7.2 `-O1`
colour interpolation (four byte stores in front of the timer byte it reads) that one edit was 1200 -> 200.

The hypothesis for the fold (cse substituting the symbol's address into `p[-k]` but not into the derived pointer) is
from the measured output, not read from the compiler. The rewrite is the same access spelled from another base."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'negative_offset_base'
FAMILIES = (FAMILY,)
SCALAR = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int|f32|float)'
MAXIMUM = 0x400


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.body
    if re.search(r'\b(?:asm|__asm__)\b', body):
        return []
    result = []
    declared = re.finditer(rf'(?<=[;{{}}])(?P<indent>\s*)(?P<type>{SCALAR})\s*\*\s*(?P<name>{IDENT})'
                           rf'\s*(?P<init>=\s*&?\s*{IDENT}\s*)?;', '{' + body)
    base = part.opening  # '{' + body starts at the opening brace
    for decl in declared:
        pointer, kind = decl['name'], decl['type']
        text = '{' + body
        below = list(re.finditer(rf'(?<![\w.>]){pointer}\s*\[\s*-\s*(\d+|0[xX][0-9a-fA-F]+)\s*\]', text))
        if not below:
            continue
        assigned = list(re.finditer(rf'(?<![\w.>]){pointer}\s*(?:=(?!=)|\+=|-=|\+\+|--)|(?:\+\+|--|&)\s*{pointer}\b'
                                    r'(?!\s*\[)', text[decl.end():]))
        distance = max(int(hit[1], 0) for hit in below)
        if not 0 < distance <= MAXIMUM:
            continue
        head = f'{pointer}_head'
        if re.search(rf'\b{head}\b', part.clean):
            continue
        spans = [(base + hit.start(), base + hit.end(), f'{head}[{distance - int(hit[1], 0)}]') for hit in below]
        indent = decl['indent'] if '\n' in decl['indent'] else '\n    '
        indent = '\n' + indent.split('\n')[-1]
        if decl['init']:
            if assigned:
                continue
            at = base + decl.end()
            spans.append((at, at, f'{indent}{kind} *{head} = {pointer} - {distance};'))
        else:
            if len(assigned) != 1:
                continue
            start = decl.end() + assigned[0].start()
            stop = text.find(';', start)
            previous = max(text.rfind(c, 0, start) for c in ';{}')
            # only a plain `p = ...;` statement of its own, in the function's outer block, before every use
            if (stop < 0 or text[previous + 1:start].strip() or not re.match(rf'{pointer}\s*=(?!=)', text[start:])
                    or text[:start].count('{') - text[:start].count('}') != 1
                    or any(hit.start() < stop for hit in below)):
                continue
            spans.append((base + decl.end(), base + decl.end(), f'{indent}{kind} *{head};'))
            spans.append((base + stop + 1, base + stop + 1, f'{indent}{head} = {pointer} - {distance};'))
        result.append((FAMILY, edit(source, spans)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
