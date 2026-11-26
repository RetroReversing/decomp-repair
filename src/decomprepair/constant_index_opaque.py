"""A constant array index the compiler never folds: a dead two-arm assignment between its set and its first use.

A target that sets an index register (`li $v1, 2`) and then computes `index * stride` with shifts and adds at run
time, where every plain spelling of the C folds `array[2]` to a constant offset. GCC 2.7.2 at `-O1` folds the value in
cse (one extended block) or in combine (one basic block). A statement that leaves two arms between the set and the use
puts labels there, so neither pass sees the value; its result is never read, so flow deletes it and the jump pass
after reload removes the empty branch. No instruction of it reaches the code: `i = 2; unused = arg0 ? 1 : 2;
D[i].a = 0; ...` matched a 46-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O1`) that stood at
245 with search scaffolding: plain `D[2]` scored 4090, the dead assignment 0. The explanation is a hypothesis from the
passes' sources and the measured variants; the exact judge decides every child. The dead local is scaffolding: the
program is unchanged, but the original source is not known to have held it.

Two shapes: a local set to a constant and later used as an index gets the dead assignment after its set; a literal
index repeated three times or more is first named in a local. The dead assignment needs a value the compiler can't
know, so the function must have a parameter.
"""
import re

from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, edit, view

FAMILY = 'constant_index_opaque'
FAMILIES = (FAMILY,)
LIMIT = 4
_NUMBER = r'(?:0[xX][0-9A-Fa-f]+|[1-9]\d*)'
_SET = re.compile(rf'(?<![\w.>])(?P<var>{IDENT})\s*=(?!=)\s*(?P<k>{_NUMBER})\s*;')
_LITERAL = re.compile(rf'\[\s*(?P<k>{_NUMBER})\s*\]')


def _parameter(part, name):
    """The first named parameter of the function, or None."""
    head = list(re.finditer(rf'(?<![\w]){re.escape(name)}\s*\(', part.clean[:part.opening]))
    if not head:
        return None
    inside = part.clean[head[-1].end():part.opening].rsplit(')', 1)[0]
    for piece in inside.split(','):
        words = re.findall(IDENT, piece)
        if len(words) >= 2 and '(' not in piece and '[' not in piece:
            return words[-1]
    return None


def _statement_start(clean, at, opening):
    """Where the statement holding `at` begins: after the last `;`, `{` or `}` before it."""
    back = max(clean.rfind(mark, opening, at) for mark in ';{}')
    start = back + 1
    while clean[start].isspace():
        start += 1
    return start


def _indent(source, at):
    return re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:at])[0] or '    '


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    parameter = _parameter(part, name)
    if not parameter:
        return []
    unused = fresh(source, header, 'unused_choice')
    declare = (opening + 1, opening + 1, f'\n    int {unused};')
    choice = f'{unused} = {parameter} ? 1 : 2;'
    out = []
    for hit in _SET.finditer(clean, opening, end):
        var = hit['var']
        if clean[:hit.start()].rstrip()[-1:] not in ';{}' or not re.search(rf'\[\s*{var}\s*\]', clean[hit.end():end]):
            continue
        after = f'\n{_indent(source, hit.start())}{choice}'
        out.append((FAMILY, edit(source, [declare, (hit.end(), hit.end(), after)])))
        if len(out) >= LIMIT:
            return out
    uses = {}
    for hit in _LITERAL.finditer(clean, opening, end):
        # an index, not the length of a declared array: what precedes the `[` is an array the statement reads
        start = _statement_start(clean, hit.start(), opening)
        if re.match(r'(?:extern|static|char|short|int|long|float|double|unsigned|signed|struct|union|[us](?:8|16|32|64)|f32|f64)\b', clean[start:]):
            continue
        uses.setdefault(hit['k'], []).append(hit)
    for value, hits in sorted(uses.items(), key=lambda item: -len(item[1])):
        if len(hits) < 3 or len(out) >= LIMIT:
            continue
        index = fresh(source, header, 'record_index')
        at = _statement_start(clean, hits[0].start(), opening)
        indent = _indent(source, at)
        edits = [(opening + 1, opening + 1, f'\n    int {index};\n    int {unused};'),
                 (at, at, f'{index} = {value};\n{indent}{choice}\n{indent}')]
        edits += [(h.start(), h.end(), f'[{index}]') for h in hits]
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 95}  # the registry: no caller wiring (registry.py)
