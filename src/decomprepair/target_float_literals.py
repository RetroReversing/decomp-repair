"""The function's literals written as the single-precision constants the target builds.

Two copies of one function often differ in how a constant was typed: one does its arithmetic in double (`x * 3.14 /
180.0`, `cvt.d.s`, `mul.d`, a pool load), its sibling in float with a finer pi (`x * 3.1415927f / 180.0f`, `lui $at,
0x4049; ori $at, 0x0FDB; mtc1`, `mul.s`). A C taken from the matched one keeps the double spelling and differs in every
instruction of the expression. The target says which float words it builds (`lui` with an optional `ori`, moved to a
float register), so each literal close to one of them is written as that word with an `f` suffix: `3.14` and `3.14f` as
`3.1415927f`, `4.0` as `4.0f`. A second child also writes an integer literal that is a factor or divisor as the float
the target builds (`i * 45` as `i * 45.0f`: the product is `cvt.s.w; mul.s`, not an integer multiply). On a
151-instruction trig setup taken from its matched sibling: 3185 under the sibling's spelling, 0 with the second child.

One child per set, all literals together: they only pay off together. Nothing is proposed unless the target does
single-precision arithmetic and builds the constant."""
import re
import struct

from .integer_repair_support import edit, view

FAMILY = 'target_float_literals'
FAMILIES = (FAMILY,)

CLOSE = 0.002  # how near a literal must be to a target word to be a spelling of it (3.14 for pi is 0.05%)

_LUI = re.compile(r'\blui\s+(\$\w+)\s*,\s*(?:\(\s*0x([0-9A-Fa-f]+)\s*>>\s*16\s*\)|(0x[0-9A-Fa-f]+|\d+))')
_ORI = re.compile(r'\bori\s+(\$\w+)\s*,\s*\1\s*,\s*(?:\(\s*0x[0-9A-Fa-f]+\s*&\s*0xFFFF\s*\)|(0x[0-9A-Fa-f]+|\d+))')
_SINGLE = re.compile(r'\b(?:add|sub|mul|div)\.s\b|\bc\.\w+\.s\b')
_NUMBER = re.compile(r'(?<![\w.])((?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+|\d+)([fF]?)(?![\w.])')


def _value(bits):
    return struct.unpack('>f', struct.pack('>I', bits))[0]


def target_floats(asm):
    """The float words the target builds in a register and moves to the FPU, as numbers."""
    lines = [re.sub(r'/\*.*?\*/', ' ', line).strip() for line in (asm or '').splitlines()]
    lines = [line for line in lines if line]
    found = []
    for at, line in enumerate(lines):
        high = _LUI.search(line)
        if not high:
            continue
        register = high[1]
        bits = int(high[2], 16) if high[2] else (int(high[3], 0) & 0xFFFF) << 16
        for later in lines[at + 1:at + 4]:
            low = _ORI.search(later)
            if low and low[1] == register:
                bits = bits if high[2] else bits | (int(low[2], 0) & 0xFFFF if low[2] else 0)
                continue
            if re.search(r'\bmtc1\s+' + re.escape(register) + r'\s*,', later):
                value = _value(bits)
                if 1e-6 < abs(value) < 1e9 and value not in found:
                    found.append(value)
                break
    return found


def spelled(value):
    """The shortest float literal with exactly this value's single-precision bits."""
    bits = struct.pack('>f', value)
    for precision in range(1, 10):
        text = f'{value:.{precision}g}'
        if struct.pack('>f', float(text)) == bits:
            break
    if 'e' in text:
        text = repr(float(text))
    if '.' not in text and 'e' not in text:
        text += '.0'
    return text + 'f'


def _factor(clean, start, end):
    """True when the number is an operand of `*` or `/` and not inside an index."""
    before = clean[:start].rstrip()
    after = clean[end:].lstrip()
    scaled = (before.endswith(('*', '/')) and re.search(r'[\w)\]]\s*[*/]$', before)) or after.startswith(('*', '/'))
    if not scaled:
        return False
    depth = 0
    for char in clean[max(0, start - 200):start]:
        depth += (char == '[') - (char == ']')
    return depth <= 0


def variants(source, name, asm=''):
    """Proposals: the float-typed literals as the target's words; then those with the integer factors too."""
    if not asm or not _SINGLE.search(asm):
        return []
    part = view(source, name)
    if not part:
        return []
    words = target_floats(asm)
    if not words:
        return []
    floats, integers = [], []
    body = part.clean[part.opening:part.end]
    for match in _NUMBER.finditer(body):
        number, suffix = match[1], match[2]
        start, end = part.opening + match.start(), part.opening + match.end()
        value = float(number)
        near = [w for w in words if value and abs(abs(w) - value) <= value * CLOSE and w > 0]
        if not near:
            continue
        word = min(near, key=lambda w: abs(w - value))
        text = spelled(word)
        if source[start:end] == text:
            continue
        if re.fullmatch(r'\d+', number) and not suffix:
            if value >= 2 and word == value and _factor(part.clean, start, end):
                integers.append((start, end, text))
        else:
            floats.append((start, end, text))
    out = []
    if floats:
        out.append((FAMILY, edit(source, floats)))
    if integers:
        out.append((FAMILY, edit(source, floats + integers)))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'),
          'order': 60, 'archs': ('mips',)}
