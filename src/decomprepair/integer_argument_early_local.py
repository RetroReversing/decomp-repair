"""An integer literal call argument held in a local that is set ahead of an unrelated statement.

    temp_s2 = arg0 + 0xD4;                      k46 = 0x46;
    obj->x = f(temp_s2, &D, 0x64, ..., 0x46);   temp_s2 = arg0 + 0xD4;
                                                obj->x = f(temp_s2, &D, 0x64, ..., k46);

KMC GCC 2.7.2 loads a literal argument where the call needs it, next to the other argument set-up. A developer's
`k46 = 0x46;` written a statement or two above (before an unrelated sum, a store) is a pseudo of its own that is live from
its set to the call: the load becomes a separate insn the scheduler places with the statements around it, ahead of the sum
the literal's own spelling would follow. A N64 constructor with an eleven-argument call (the last argument a stack
word) stood at 225 with the literal inline and was exact (0) with `s32 k46; k46 = 0x46;` set before the
`temp_s2 = arg0 + 0xD4;` line and the stack argument written `k46`. `constant_in_local_argument` is the float form of the
same step and sets the local only on the line before the statement; this one offers the integer form and walks the set
back over the earlier statements of the block, since the target's order decides how far.

Children, one local and one place each: a literal other than 0 and 1 (those come from `$zero` or a shared register) passed
to a call as a bare argument, in a plain statement; `k_<literal> = <literal>;` goes before the call's own statement and
before each of up to three plain statements above it in the same block (never across a brace, an `if`/loop or a
declaration), and the argument reads the local. Stack arguments (the fifth and later) come first, since a register
argument is set right at the call. The local is declared `s32` after the leading declarations.

Gate: when the target's assembly is given, the literal must be loaded by an immediate (`li`, `addiu $r, $zero, K`,
`ori $r, $zero, K`) in the target; without it the judge alone decides. Nothing is offered for a function with
`volatile`, `asm` or a preprocessor line. Hypothesis, not confirmed in the compiler source: the early set is a
separate pseudo whose load the scheduler keeps in source order against the statements it was written above."""
import re

from .constant_in_local import _CALL_ARGUMENT, _INT, _NOT_STATEMENT, _STATEMENT, _int, _name
from .integer_repair_support import IDENT, edit, view
from .store_run_order import _insert_declaration

FAMILY = 'integer_argument_early_local'
FAMILIES = (FAMILY,)
LIMIT = 32
BACK = 3
_ARGUMENT = re.compile(rf'(?:^|,)\s*(?P<k>{_INT})\s*(?=,|$)')


def _loaded(asm, value):
    """True when the target has an immediate load of `value` (decimal or hex, signed or not)."""
    if not asm:
        return True
    forms = {str(value), hex(value), f'0x{value:X}'}
    for hit in re.finditer(r'\b(?:li|addiu|ori)\s+\$\w+\s*,\s*(?:\$zero\s*,\s*)?(-?\w+)', asm):
        try:
            if int(hit[1], 0) == value or hit[1] in forms:
                return True
        except ValueError:
            continue
    return False


def _declaration(text):
    return '(' not in text and '=' not in text


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', body[part.opening:part.end], re.M):
        return []
    used = set(re.findall(IDENT, body[part.opening:part.end]))
    statements = [hit for hit in _STATEMENT.finditer(body, part.opening + 1, part.end)
                  if body[:hit.start(1)].rstrip()[-1:] in ('', ';', '{', '}')]
    stack, register = [], []
    for index, hit in enumerate(statements):
        text = hit[2]
        first = re.match(r'\s*(\w+)', text)
        if not first or first[1] in _NOT_STATEMENT or _declaration(text):
            continue
        for call in _CALL_ARGUMENT.finditer(text):
            callee = call['callee']
            if callee in _NOT_STATEMENT or callee == 'sizeof' or callee.startswith('M2C_') or callee.isupper():
                continue
            for argument in _ARGUMENT.finditer(call['args']):
                literal = argument['k']
                value = _int(literal)
                if value in (0, 1) or not _loaded(asm, value):
                    continue
                index_of = call['args'][:argument.start('k')].count(',')
                (stack if index_of >= 4 else register).append((index, hit, call, argument, literal))
    out, done = [], set()
    for index, hit, call, argument, literal in stack + register:
        local = _name('k', literal)
        if local in used or (index, literal) in done:
            continue
        done.add((index, literal))
        at = hit.start(2) + call.start('args') + argument.start('k')
        spots = [index]
        for back in range(index - 1, max(index - BACK, 0) - 1, -1):
            earlier = statements[back]
            between = body[earlier.end():statements[back + 1].start(1)]
            first = re.match(r'\s*(\w+)', earlier[2])
            if '{' in between or '}' in between or not first or first[1] in _NOT_STATEMENT or _declaration(earlier[2]):
                break
            spots.append(back)
        for spot in spots:
            target = statements[spot]
            child = edit(source, [(at, at + len(literal), local),
                                  (target.start(2), target.start(2), f'{local} = {literal};\n{target[1]}')])
            moved = view(child, name)
            if moved:
                out.append((FAMILY, _insert_declaration(child, moved, f's32 {local};')))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
