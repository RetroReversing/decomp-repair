"""m2c's `(0 & 0x10)`: a flag the game held in a register, set to zero and tested later.

m2c propagates the zero into the test, and the compiler then folds the whole test away: the register's `move $s0,
$zero` before the calls and the `andi $v0,$s0,0x10` after them are missing. The original held the value in a local (a
button mask a build left at zero), assigned somewhere before the test:

    if (G == 0x10E) {                     s32 zero_flag;
        f(2);                             ...
    }                                     zero_flag = 0;
    if (G >= 0x186 || (0 & 0x10)) {  ->   if (G == 0x10E) { f(2); }
                                          if (G >= 0x186 || (zero_flag & 0x10)) {

Variants set it before the statement ahead of the test (a case label's first statement when the test is in a switch arm),
directly before the test, and once at the function's head. A 142-instruction N64 state routine (KMC GCC 2.7.2, `-O1`)
went from 2965 to 1620 with this, on the way to exact.
"""
import re

from .csource import _blank, find

FAMILY = 'folded_zero_flag'
FAMILIES = (FAMILY,)
NAME = 'zero_flag'
_USE = re.compile(r'\(\s*0\s*&\s*(0[xX][0-9A-Fa-f]+|[1-9]\d*)\s*\)')
_LABEL = re.compile(r'(?m)^[ \t]*(?:case\b[^:\n]*|default[ \t]*):[ \t]*\n')


def _statements(body, at):
    """The offsets where the statements of the block holding `at` begin, up to the one holding `at`."""
    depth, opening = 0, -1
    for i in range(at, -1, -1):
        if body[i] == '}':
            depth += 1
        elif body[i] == '{':
            if not depth:
                opening = i
                break
            depth -= 1
    if opening < 0:
        return []
    starts, depth, begin = [], 0, True
    for i in range(opening + 1, at + 1):
        ch = body[i]
        if begin and not ch.isspace() and not depth:
            if not body.startswith('else', i):
                starts.append(i)
            begin = False
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
            begin = begin or (ch == '}' and not depth)
        elif ch in ';:' and not depth:
            begin = True
    return starts


def variants(source, name):
    span = find(source, name)
    if not span or re.search(r'\b' + NAME + r'\b', source):
        return []
    body = _blank(source[span[0]:span[1]])
    uses = list(_USE.finditer(body))
    opening = body.find('{')
    if not uses or opening < 0:
        return []
    placements = [[], [], []]  # before the earlier statement, before the test, at the function's head
    for use in uses:
        starts = _statements(body, use.start())
        if not starts:
            return []
        test = starts[-1]
        labels = [m.end() for m in _LABEL.finditer(body, 0, test)]
        earlier = starts[-2] if len(starts) > 1 else test
        if labels and labels[-1] > earlier:
            earlier = labels[-1]
        placements[0].append(earlier)
        placements[1].append(test)
    head = opening + 1
    declarations = re.compile(r'\s*(?:(?!return\b)[A-Za-z_]\w*[\s*]+)+[A-Za-z_]\w*\s*(?:\[[^\]\n]*\]\s*)*;')
    while (found := declarations.match(body, head)):
        head = found.end()
    placements[2].append(head)
    original = source[span[0]:span[1]]
    out, seen = [], set()
    for places in placements:
        edits = [(m.start(), m.end(), f'({NAME} & {m[1]})') for m in uses]
        for at in sorted(set(places)):
            line = original.rfind('\n', 0, at) + 1
            if original[line:at].strip():
                at_line = original.find('\n', at - 1) + 1 if original[at - 1] != '\n' else at
                edits.append((at_line, at_line, f'    {NAME} = 0;\n'))
            else:
                indent = re.match(r'[ \t]*', original[line:])[0]
                edits.append((line, line, f'{indent}{NAME} = 0;\n'))
        edits.append((opening + 1, opening + 1, f'\n    s32 {NAME};'))
        text = original
        for a, b, replacement in sorted(edits, reverse=True):
            text = text[:a] + replacement + text[b:]
        if text not in seen:
            seen.add(text)
            out.append((FAMILY, source[:span[0]] + text + source[span[1]:]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
