"""`if (p < (v = E)) { v = (s32) p; }`: the assignment taken out of the test and the narrow parameter copied to a local.

    if (arg2 < (var_a0 = E)) { var_a0 = (s32) arg2; }
->  var_a0 = E;   arg2c = (s32) arg2;   if (arg2c < var_a0) { var_a0 = arg2c; }

m2c folds the clamp `v = min(E, p)` into an assignment inside the condition. The game computed the value, read the
(halfword) parameter into a local of its own, then compared the two, so the parameter's sign extension is one insn the
scheduler places by the local's statement. The last rows of a N64 clamp-and-slew routine (KMC GCC 2.7.2 `-O1`, 85
instructions) were those: 10 -> 0 with `s32 arg2c`.

Children, per site (a condition `P < (V = E)` or `>`, `<=`, `>=`, with an arm that is exactly `V = P;` or
`V = (s32) P;`): the form with the new local `<P>c` (declared `s32` after the leading declarations), and the same split
reading `P` itself. Proposals only; the compiler and the byte judge decide."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close
from .store_run_order import _insert_declaration

FAMILY = 'condition_assignment_param_local'
FAMILIES = (FAMILY,)
_HEAD = re.compile(rf'\bif\s*\(\s*(?P<p>{IDENT})\s*(?P<op><=|>=|<|>)\s*\(\s*(?P<v>{IDENT})\s*=\s*')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean
    out = []
    for head in _HEAD.finditer(body, part.opening, part.end):
        # the `(` that opens the assignment is the second one of the head
        first = body.index('(', head.start())
        second = body.index('(', first + 1)
        stop = close(body, second)
        if not stop:
            continue
        expression = source[head.end():stop - 1].strip()
        tail = re.compile(rf'\s*\)\s*\)\s*{{\s*{head["v"]}\s*=\s*(?:\(\s*s32\s*\)\s*)?{head["p"]}\s*;\s*}}')
        arm = tail.match(body, stop - 1)
        if not arm or not expression:
            continue
        p, v, op = head['p'], head['v'], head['op']
        lead = re.search(r'([ \t]*)$', source[:head.start()])[1]
        local = f'{p}c'
        if local in re.findall(IDENT, body[part.opening:part.end]):
            continue
        for use, copy in ((local, f'{local} = (s32) {p};\n{lead}'), (p, '')):
            new = (f'{v} = {expression};\n{lead}{copy}if ({use} {op} {v}) {{\n{lead}    {v} = {use};\n{lead}}}')
            child = edit(source, [(head.start(), arm.end(), new)])
            moved = view(child, name)
            if moved:
                out.append((FAMILY, _insert_declaration(child, moved, f's32 {local};') if use == local else child))
    return list(dict.fromkeys(out))[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
