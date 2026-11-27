"""A float local's arithmetic done in place before the call that takes its integer value.

    f(a, (s32) (temp / D_SCALE));        ->        temp = temp / D_SCALE;   f(a, (s32) temp);

m2c writes the divided float inside the converted argument. The game stored the quotient back in the local that held
the dividend, as its own statement, so the conversion reads one float register the division left and the argument
set-up that sign-extends a narrow parameter (`D_TABLE[arg0]`) comes after the division. A N64 clamp-and-slew routine
(KMC GCC 2.7.2 `-O1`, 85 instructions) stood at 190 with the quotient inline and was at 10 with the in-place statement
(the last rows were the parameter's own copy, `condition_assignment_param_local`).

Children: for a statement `callee(..., (s32) (X OP Y), ...);` (cast to a 32-bit integer, OP one of `/ * + -`, X a local
declared `f32`/`f64`/`float`/`double` in the function, Y an identifier, member or number) that is the last place X is
read, `X = X OP Y;` goes on the line before and the argument reads `(s32) X`. One child per site. Nothing is offered for
a function with `volatile`, `asm` or a preprocessor line. Proposals only; the compiler and the byte judge decide."""
import re

from .constant_in_local import _STATEMENT
from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_quotient_argument_stage'
FAMILIES = (FAMILY,)
LIMIT = 6
_CAST = re.compile(rf'\(\s*(?:s32|int|u32|unsigned\s+int)\s*\)\s*\(\s*(?P<x>{IDENT})\s*(?P<op>[/*+-])\s*(?P<y>{IDENT}(?:\s*(?:\.|->)\s*{IDENT})*|[0-9.]+f?)\s*\)')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body[part.opening:part.end], re.M):
        return []
    text = body[part.opening:part.end]
    floats = set(re.findall(rf'\b(?:f32|f64|float|double)\s+({IDENT})\s*;', text))
    out = []
    for hit in _STATEMENT.finditer(body, part.opening + 1, part.end):
        statement = hit[2]
        for cast in _CAST.finditer(statement):
            x = cast['x']
            if x not in floats or not re.search(rf'{IDENT}\s*\(', statement[:cast.start()]):
                continue
            if re.search(rf'\b{x}\b', body[hit.end():part.end]):
                continue
            at = hit.start(2) + cast.start()
            fixed = f'(s32) {x}'
            line = f'{x} = {x} {cast["op"]} {cast["y"]};\n{hit[1]}'
            out.append((FAMILY, edit(source, [(hit.start(2), hit.start(2), line), (at, at + cast.end() - cast.start(), fixed)])))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
