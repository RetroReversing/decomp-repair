"""A float constant the target puts in `$f12` for a callee m2c declared without parameters.

m2c writes `callee();` when it sees no integer argument register set before the `jal`. A game that called
`callee(60.0f)` sets the float in `$f12` instead (`lui $at, 0x4270; mtc1 $at, $f12`), which m2c does not read as an
argument, so the C has no `lui`/`mtc1` pair at all and its function is two instructions short at each call. The
target says what was passed: the constant loaded into `$f12` in the few instructions before each `jal`.

For a callee whose prototype in the source has no parameters (`()` or `(void)`) and whose every C call has no
arguments, when the target's calls to it (as many as the C's) each load a short ordinary float into `$f12`, the
prototype gains one `f32` parameter and each call passes its constant, in order. Only o32 argument registers
(`-mgp32`, `-mabi=32`); only prototypes the source declares itself.
"""
import re

from .csource import _blank, find
from .float_bit_argument_repairs import float_text
from .mips_returns import instructions
from .pattern_repairs import close

FAMILY = 'float_register_argument'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
WINDOW = 12
# (splat writes `lui $at, (0x42700000 >> 16)` and `$fa0` for `$f12`)
_LUI = re.compile(r'lui\s+\$(\w+),\s*(?:\(\s*(0[xX][0-9a-fA-F]+)\s*>>\s*16\s*\)|(0[xX][0-9a-fA-F]+|\d+))$')
_ORI = re.compile(r'ori\s+\$(\w+),\s*\$(\w+),\s*(?:\(\s*(0[xX][0-9a-fA-F]+)\s*&\s*0[xX][fF]+\s*\)|(0[xX][0-9a-fA-F]+|\d+))$')
_MTC1 = re.compile(r'mtc1\s+\$(\w+),\s*\$(?:f12|fa0)$')
_JAL = re.compile(r'jal\s+(' + IDENT + r')$')


def float_calls(asm):
    """{callee: [bits of the constant put in $f12 before each call, or None]}, in call order."""
    rows = instructions(asm)
    found = {}
    for index, row in enumerate(rows):
        call = _JAL.fullmatch(row)
        if not call:
            continue
        bits = None
        for at in range(index + 1, max(index - WINDOW, -1), -1):
            if at >= len(rows):
                continue
            if _JAL.fullmatch(rows[at]) and at != index:
                break
            move = _MTC1.fullmatch(rows[at])
            if not move:
                continue
            register, low = move[1], 0
            for back in range(at - 1, max(at - WINDOW, -1), -1):
                ori = _ORI.fullmatch(rows[back])
                if ori and ori[1] == register and ori[2] == register:
                    low = int(ori[3], 0) & 0xFFFF if ori[3] else int(ori[4], 0)
                    continue
                lui = _LUI.fullmatch(rows[back])
                if lui and lui[1] == register:
                    bits = ((int(lui[2], 0) >> 16 << 16) | low) if lui[2] else ((int(lui[3], 0) << 16) | low)
                    break
            break
        found.setdefault(call[1], []).append(bits)
    return found


def variants(source, name, asm, flags=()):
    flags = set(flags)
    if flags and not flags & {'-mgp32', '-mabi=32'}:
        return []
    constants = {callee: bits for callee, bits in float_calls(asm).items() if bits and all(b is not None for b in bits)}
    span = find(source, name)
    if not constants or not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    result = []
    for callee, bits in constants.items():
        texts = [float_text(b) for b in bits]
        if callee == name or None in texts:
            continue
        prototypes = [hit for hit in re.finditer(r'(?m)^[ \t]*(?:extern\s+)?(?:' + IDENT + r'[\s*]+)+' + re.escape(callee)
                                                  + r'\s*\(\s*(?:void)?\s*\)\s*;', clean) if not span[0] <= hit.start() < span[1]]
        calls = []
        for hit in re.finditer(r'(?<![\w.>])' + re.escape(callee) + r'\s*\(', clean[opening:span[1]]):
            start = opening + hit.end() - 1
            end = close(clean, start)
            if not end or clean[start + 1:end - 1].strip() not in ('', 'void'):
                calls = None
                break
            calls.append((start, end))
        if len(prototypes) != 1 or not calls or len(calls) != len(texts):
            continue
        edits = [(start + 1, end - 1, text) for (start, end), text in zip(calls, texts)]
        proto = prototypes[0]
        parenthesis = source.index('(', proto.start() + source[proto.start():proto.end()].index(callee))
        edits.append((parenthesis + 1, source.index(')', parenthesis), 'f32'))
        text = source
        for a, b, replacement in sorted(edits, reverse=True):
            text = text[:a] + replacement + text[b:]
        result.append((FAMILY, text))
    return result
