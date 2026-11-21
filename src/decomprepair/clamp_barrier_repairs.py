"""A clamp whose difference the target computes twice (KMC GCC 2.7.2).

m2c writes a range clamp as `t = x - 0x20; if (t >= 0) { v = x - 0x20; if (t >= 0x25) v = 0x24; } else v = 0;`.
cse sees the second `x - 0x20` as the first one's value and the compiler emits `move v, t` (a branch-likely arm
with the copy in its slot). The target's clamps instead read `addiu v0,v1,-0x20; bltz v0,..; slti v0,v0,0x25; bnez;
addiu v1,v1,-0x20 ...`: the difference is computed twice, the second one in the branch's delay slot. A source
that spells the first difference differently keeps the two apart until combine and gives that shape:

* `(s16) x - 0x20` for a byte or halfword value (the sign extension cse cannot see through, and combine drops it);
* `(x & 0xFF) - 0x20` for a value that is a byte of a wider word (the target's `andi v0,a1,255` before the subtract);
* `(s8) x - 0x20`, the same barrier at byte width.

Measured on a 129-instruction N64 function with four such clamps (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`):
the plain spelling scored 5535 and the `(s16)` or masked spelling 2070; the evidence is in COMPILER_MATCHING_LEARNINGS.md
of decompdecomp. A candidate rewrite, not an equivalence proof: the exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'clamp_difference_barrier'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
_OPERAND = r'[A-Za-z_]\w*'
_TEST = re.compile(
    rf'(?m)^(?P<indent>[ \t]*)(?P<test>[A-Za-z_]\w*)\s*=\s*(?P<operand>{_OPERAND})\s*-\s*(?P<const>{_NUMBER})\s*;[ \t]*\n')
_BARRIERS = ('(s16) {x}', '({x} & 0xFF)', '(s8) {x}')


def _mixed(clean, start, operand):
    """The barrier that suits how the operand was made: a middle byte of a word or a halfword takes the mask the
    target kept (`andi v0,a1,255`), a top byte or a byte load the sign extension."""
    before = clean[:start]
    assign = list(re.finditer(rf'(?<![\w.>]){re.escape(operand)}\s*=(?!=)\s*([^;]*);', before))
    text = assign[-1][1] if assign else ''
    if re.search(r'>>\s*(?:8|16)\b|&\s*0[xX]F{4}\b|\(\s*u16\s*\)|\bu16\b|\bH\s*\(', text):
        return _BARRIERS[1]
    return _BARRIERS[0]


def sites(source, name):
    """Every clamp in the function whose first difference can be kept apart: (start, end, indent, test, operand, const)."""
    part = view(source, name)
    if not part:
        return [], None
    clean = part.clean
    found = []
    for m in _TEST.finditer(clean, part.opening + 1, part.end - 1):
        test, operand, const = m['test'], m['operand'], m['const']
        if test == operand:
            continue
        # the very next statement guards on the difference being non-negative
        guard = re.match(rf'[ \t]*if\s*\(\s*{test}\s*>=\s*0\s*\)\s*{{?', clean[m.end():m.end() + 80])
        if not guard:
            continue
        arm = clean[m.end() + guard.end():m.end() + guard.end() + 240]
        # the arm recomputes the same difference from the same operand (the copy cse would fold)
        again = re.search(rf'\b\w+\s*=\s*{re.escape(operand)}\s*-\s*{re.escape(const)}\s*;', arm)
        if not again:
            continue
        # and the operand is not changed on the way (then it is not the same value)
        if re.search(rf'(?<![\w.>]){re.escape(operand)}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|[+-]{{2}}\s*{re.escape(operand)}\b'
                     rf'|\b{re.escape(operand)}\s*[+-]{{2}}', arm[:again.start()]):
            continue
        found.append((m.start(), m.end(), m['indent'], test, operand, const))
    return found, clean


def variants(source, name, limit=12):
    """One child per site and style, then every site at once in each style and in the mixed style: the target's
    clamps came together, and one alone left the score unchanged."""
    found, clean = sites(source, name)
    result = []
    for start, end, indent, test, operand, const in found:
        for barrier in _BARRIERS:
            text = f"{indent}{test} = {barrier.format(x=operand)} - {const};\n"
            result.append((FAMILY, edit(source, [(start, end, text)])))
    combined = []
    if len(found) > 1:
        for style in (0, 1, 2, 'mixed'):
            edits = []
            for start, end, indent, test, operand, const in found:
                barrier = _mixed(clean, start, operand) if style == 'mixed' else _BARRIERS[style]
                edits.append((start, end, f"{indent}{test} = {barrier.format(x=operand)} - {const};\n"))
            combined.append((FAMILY, edit(source, edits)))
    return (combined + result)[:limit]
