"""A float literal m2c held in a local set before a loop, written where the loop reads it.

GCC's loop pass moves a float constant's load out of the loop into a saved float register, and m2c prints what it sees:
`temp_fs1 = 10000.0f;` before the loop and `temp_fs1` at each use. A user local set before the loop is scheduled and
ranked unlike the pass's own hoisted register, so the game's literal at each use compiles to other bytes. The loop pass
only does that in a real loop: a draft that spells the loop as `label: if (c) { ...; goto label; }` gets nothing
hoisted from literals written inside it, so the two edits only pay off together (and `while (c)` rotates the loop, which
a target with its test at the top and a `j` at the bottom did not do).

`for (;;)` is not the same here: SN GCC 2.8.1 moved its break test to the bottom (score 1195 against `while (1)`'s 0).

Measured on a 70-instruction N64 model-radius function (SN GCC 2.8.1, -G0 -mips3 -O2 -mfp32): from the draft with the
literal in its local (score 40), the loop form alone scored 60, the literal inline alone 717, both together 0.

Children, for a `float`/`double` local assigned exactly once, a plain float literal, never address-taken, read only
after the assignment and at least once inside a loop:
- `loop_float_literal_inline_break`: a goto loop around reads written `while (1) { if (!(c)) break; ... }`, with every
  such literal written at its reads (offered only when the body holds no `break` or `continue` of its own and the label
  has no other `goto`);
- `loop_float_literal_inline`: the literals written at their reads, for a source whose loops are already real loops.
Which loop forms the compiler hoists from is read off these scores, not from its source: a hypothesis."""
import re

from .arm_block_support import IDENT, brace_pairs
from .integer_repair_support import edit, view

FAMILY = 'loop_float_literal_inline'
FAMILIES = (FAMILY, FAMILY + '_break')

DECLARATION = re.compile(rf'(?m)^[ \t]*(?:f32|f64|float|double)[ \t]+(?P<n>{IDENT})[ \t]*;[ \t]*\n')
LITERAL = r'(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fF]?'
GOTO_LOOP = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<label>{IDENT}):[ \t]*\n[ \t]*if[ \t]*\(')
REAL_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')


def _closing_paren(clean, opening, end):
    depth = 0
    for i in range(opening, end):
        depth += (clean[i] == '(') - (clean[i] == ')')
        if depth == 0:
            return i
    return None


def _goto_loops(part, pairs):
    """[(label start, `if` condition span, body brace, its closing brace, the back `goto` span)]"""
    clean, found = part.clean, []
    for hit in GOTO_LOOP.finditer(clean, part.opening, part.end):
        opening = hit.end() - 1
        closing = _closing_paren(clean, opening, part.end)
        if closing is None:
            continue
        brace = re.compile(r'\s*\{').match(clean, closing + 1)
        if not brace:
            continue
        body = brace.end() - 1
        last = pairs.get(body)
        if last is None or re.compile(r'\s*else\b').match(clean, last + 1):
            continue
        back = re.search(rf'[ \t]*\bgoto\s+{hit["label"]}\s*;[ \t]*\n?(?=\s*\Z)', clean[body + 1:last])
        if not back or len(re.findall(rf'\bgoto\s+{hit["label"]}\b', clean[part.opening:part.end])) != 1:
            continue
        if re.search(r'\b(?:break|continue)\b', clean[body + 1:last]):
            continue
        found.append((hit.start(), (opening + 1, closing), body, last, (body + 1 + back.start(), body + 1 + back.end())))
    return found


def _real_loops(part, pairs):
    spans = []
    for hit in REAL_LOOP.finditer(part.clean, part.opening, part.end):
        if hit.group().endswith('{'):
            brace = hit.end() - 1
        else:
            closing = _closing_paren(part.clean, hit.end() - 1, part.end)
            match = closing is not None and re.compile(r'\s*\{').match(part.clean, closing + 1)
            if not match:
                continue
            brace = match.end() - 1
        if brace in pairs and not (hit.group().endswith('{') and
                                   re.compile(r'\s*while\s*\(\s*0\s*\)').match(part.clean, pairs[brace] + 1)):
            spans.append((hit.start(), pairs[brace]))
    return spans


def _literals(source, part):
    """[(name, literal text, declaration span, assignment span, read starts)]"""
    clean, out = part.clean, []
    for declared in DECLARATION.finditer(clean, part.opening, part.end):
        name = declared['n']
        uses = [m for m in re.finditer(rf'(?<![\w.>]){name}\b', clean[:part.end]) if m.start() > declared.end() - 1
                and m.start() >= part.opening]
        if len(uses) < 2:
            continue
        first = uses[0]
        line = clean.rfind('\n', 0, first.start()) + 1
        assigned = re.compile(rf'[ \t]*{name}[ \t]*=[ \t]*(?P<v>{LITERAL})[ \t]*;[ \t]*\n').match(clean, line)
        if not assigned:
            continue
        reads = [m.start() for m in uses[1:]]
        written = any(re.compile(rf'{name}\s*(?:(?:[-+*/]|<<|>>)?=(?!=)|\+\+|--)').match(clean, at) or
                      re.search(r'(?:&|\+\+|--)\s*\Z', clean[part.opening:at]) and
                      not re.search(r'(?:[\w)\]]|&&)\s*&\s*\Z', clean[part.opening:at]) for at in reads)
        if written:
            continue
        value = source[assigned.start('v'):assigned.end('v')]
        out.append((name, value, (declared.start(), declared.end()), (line, assigned.end()), reads))
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    pairs = brace_pairs(part.clean, part.opening, part.end)
    if pairs is None:
        return []
    literals = _literals(source, part)
    if not literals:
        return []

    def inline(spans):
        edits = []
        for local, value, declared, assigned, reads in literals:
            if not any(low < at < high and assigned[1] <= low for at in reads for low, high in spans):
                continue
            edits += [(*declared, ''), (*assigned, '')] + [(at, at + len(local), value) for at in reads]
        return edits

    out = []
    for start, (low, high), body, last, back in _goto_loops(part, pairs):
        edits = inline([(start, last)])
        if not edits:
            continue
        lead = re.match(r'[ \t]*', source[start:]).group()
        condition = source[low:high]
        for local, value, *_ in literals:
            if any((at, at + len(local), value) in edits for at in [m.start() for m in
                   re.finditer(rf'(?<![\w.>]){local}\b', part.clean[:high]) if m.start() >= low]):
                condition = re.sub(rf'(?<![\w.>]){local}\b', value, condition)
        head = f'{lead}while (1) {{\n{lead}    if (!({condition})) {{\n{lead}        break;\n{lead}    }}'
        edits = [e for e in edits if not (start <= e[0] < body + 1)]
        edits += [(start, body + 1, head), (*back, '')]
        out.append((FAMILY + '_break', edit(source, edits)))
    edits = inline(_real_loops(part, pairs))
    if edits:
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 63}
