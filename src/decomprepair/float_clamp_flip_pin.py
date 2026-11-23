"""m2c's `(x > 0.0f) ? x : 0.0f` clamp in a loop, written the way the game clamped it: `if (x < 0.0f) x = 0.0f`, with the zero pinned.

m2c spells a lower clamp of a float read as `value = (rec->f > 0.0f) ? rec->f : 0.0f;`. Two facts about KMC GCC 2.7.2
make that the wrong source when the clamp sits in a loop:

  * The compare is `c.lt.s zero, value` (0 < value), with the zero loaded first and the value second, so the two
    floats take the other pair of registers than a compare written `value < 0.0f` (`c.lt.s value, zero`): the value in
    `$f0` and the zero in `$f2` in the game, the zero in `$f0` and the value in `$f2` here (5 register rows).
  * The compare written the game's way (`if (v < 0.0f) v = 0.0f;`) uses the zero twice (the compare and the store), and
    loop.c (`move_movables`, savings 1 and a lifetime of four insns against its threshold) then hoists the zero out of
    the loop into a saved float register, which costs a stack slot and a prologue store (`sdc1 $f24`): the same source
    scored 857 against 320. A float that is assigned in place at the compare (`v < (zero = 0.0f)`) has references in
    one block only but is a *user* pseudo that loop.c leaves alone (`float_constant_loop_pin`'s finding); the final
    code loads the zero where it is compared (`mtc1 $zero,$f2`) with nothing left of the local.

Neither half alone is the game's code (the flip alone 857, the pin alone no change), so this family writes both as one
child (320 -> 315 here, with the registers of the clamp then all matching; `float_constant_loop_pin` offered only the
pin on the ternary, 320 -> 320).

The flipped clamp differs from the ternary for a NaN value and for -0.0 (the ternary yields +0.0 for both, the `if`
keeps them): a hypothesis about how the game wrote it, not a statement about the compiler; the target's compare
direction is what the instructions show.

Offered only for a statement `local = (E > 0.0f) ? (E) : (0.0f);` inside a loop, where `E` is a plain read (names, `->`,
`.`, constant subscripts) written identically in both places and `local` is a float local of the function.

`variants` gives, labelled `float_clamp_flip_pin`, one child per such statement (and the child with every one of them).
"""
import re

from .case_temporary_repairs import _identifiers
from .csource import _blank, find
from .local_web_split import _blocks, _is_loop
from .pattern_repairs import close

FAMILY = 'float_clamp_flip_pin'
FAMILIES = (FAMILY,)
LIMIT = 6
READ = r'[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*|\s*\[\s*(?:\d+|[A-Za-z_]\w*)\s*\])*'
CLAMP = re.compile(
    rf'(?P<indent>[ \t]*)(?P<local>[A-Za-z_]\w*)\s*=\s*\(?\s*\(\s*(?P<e>{READ})\s*>\s*0(?:\.0*)?f?\s*\)\s*\?\s*\(?\s*(?P=e)\s*\)?\s*:\s*\(?\s*0(?:\.0*)?f?\s*\)?\s*\)?\s*;[ \t]*\n')


def _float_local(clean, local, opening):
    return re.search(rf'(?m)^[ \t]*(?:register\s+)?(?:f32|float)\s+{re.escape(local)}\s*;', clean[opening:]) is not None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    blocks = _blocks(clean, opening, end)
    found = []
    for m in CLAMP.finditer(clean, opening, end):
        if not _float_local(clean, m['local'], opening):
            continue
        if not any(a < m.start() < b and _is_loop(clean, (a, b)) for a, b in blocks):
            continue
        found.append(m)
    if not found:
        return []
    taken = _identifiers(source)
    zero = '__repair_zero'
    while zero in taken:
        zero += '_'
    line_end = source.index('\n', opening) + 1

    def build(chosen):
        text = source
        for m in sorted(chosen, key=lambda m: -m.start()):
            ind, local, e = m['indent'], m['local'], re.sub(r'\s+', ' ', source[m.start('e'):m.end('e')])
            new = (f'{ind}{local} = {e};\n{ind}if ({local} < ({zero} = 0.0f))\n{ind}{{\n{ind}  {local} = {zero};\n{ind}}}\n')
            text = text[:m.start()] + new + text[m.end():]
        return text[:line_end] + f'  f32 {zero};\n' + text[line_end:]

    out = [(FAMILY, build([m])) for m in found]
    if len(found) > 1:
        out.append((FAMILY, build(found)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 63}
