"""An inner loop that reads the outer loop's cursor through a copy taken when the inner loop is entered.

The outer loop steps a cursor (`cursor += 8;` after the inner loop) and the inner loop reads fields through it. GCC
2.7's loop pass treats every address built from the outer loop's induction variable as a derived induction
variable of its own, and reduces it: the inner loop gets `s3 = cursor + 4` and `lhu 2($s3)` where the target reads
`lhu 6($s4)`, and a register is spent on the derived variable. When the inner loop reads a copy of the cursor made
once when it is entered (`entry = cursor;`) the copy is an ordinary invariant of the inner loop, the target's `move
$s3,$s4` appears at the head of the inner loop's guard, and the fields are read at their plain offsets. (A 180-instruction
N64 function, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`: 1110 -> 700 with the copy alone, 931 -> 620 beside the other
repairs of that function.)

For each plain local `X` that an enclosing loop assigns or steps outside the inner loop, that the inner loop reads and
never writes, two candidates are offered: a copy `__repair_entry_X = X;` as the first statement of the inner loop's
block (the guard it sits in), and the same copy directly before the inner loop. The inner loop's reads of `X` become
the copy. A candidate for the exact judge, never a verdict."""
import re

from .integer_repair_support import IDENT, edit, view
from .loop_address_hoist_repairs import _loops

FAMILIES = ('outer_cursor_entry_copy',)
LIMIT = 8
PREFIX = '__repair_entry_'
WRITE = r'(?<![\w.>]){x}\s*(?:[-+*/&|^%]|<<|>>)?=(?!=)|\+\+\s*{x}\b|\b{x}\s*(?:\+\+|--)|--\s*{x}\b|&\s*{x}\b'


def _written(x, text):
    return re.search(WRITE.format(x=re.escape(x)), text) is not None


def _kind(clean, opening, x):
    hit = re.search(rf'(?m)^[ \t]*((?:[A-Za-z_]\w*[ \t]+)*[A-Za-z_]\w*[ \t]*\**)[ \t]*{re.escape(x)}[ \t]*;', clean[opening:])
    if not hit:
        return None
    kind = ' '.join(hit[1].replace('*', ' * ').split()).replace(' * ', ' *')
    if re.search(r'\b(?:volatile|struct|union|enum|register)\b', kind) or '[' in kind:
        return None
    return kind


def _block_head(clean, at):
    """Offset just after the `{` of the innermost block that holds offset `at`, or None."""
    depth = 0
    for pos in range(at-1, -1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos+1
            depth -= 1
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or PREFIX in part.clean:
        return []
    clean = part.clean
    spans = list(_loops(clean, part.opening, part.end))
    pairs = [(o, i) for o in spans for i in spans if o[0] < i[0] and i[1] <= o[1]]
    out = []
    seen = set()
    for outer, inner in pairs:
        outside = clean[outer[0]:inner[0]] + clean[inner[1]:outer[1]]
        inside = clean[inner[0]:inner[1]]
        for x in dict.fromkeys(re.findall(IDENT, inside)):
            if x in seen or not _written(x, outside) or _written(x, inside):
                continue
            kind = _kind(clean, part.opening, x)
            if not kind or not re.search(rf'(?<![\w.>]){re.escape(x)}\b', inside):
                continue
            local = PREFIX + x
            replaced = re.sub(rf'(?<![\w.>]){re.escape(x)}\b', local, source[inner[0]:inner[1]])
            decl = (part.opening+1, part.opening+1, f'\n  {kind}{"" if kind.endswith("*") else " "}{local};')
            head = _block_head(clean, inner[0])
            line = clean.rfind('\n', 0, inner[0])+1
            alone = not clean[line:inner[0]].strip()
            indent = re.match(r'[ \t]*', clean[line:inner[0]])[0] if alone else '  '
            places = []
            if head is not None and head > outer[0]:
                at = clean.find('\n', head)+1
                places.append((at, re.match(r'[ \t]*', clean[at:])[0] or indent))
            places.append((line if alone else inner[0], indent))
            for at, pad in places:
                out.append(edit(source, [decl, (at, at, f'{pad}{local} = {x};\n'), (inner[0], inner[1], replaced)]))
            seen.add(x)
    result = []
    for text in out:
        if text != source and text not in result:
            result.append(text)
    return [(FAMILIES[0], c) for c in result[:LIMIT]]
