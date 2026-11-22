"""Bind a generated unsigned-to-float conversion bias to its verified ROM constant."""

import re
import struct

from .integer_repair_support import IDENT, edit, view

FAMILY = 'unsigned_float_bias'
_POOL = re.compile(rf'ldc1 (\$f\d+), %lo\(({IDENT})\)\(\$at\)')
_CONVERSION = re.compile(
    r'cvt\.d\.w (\$f\d+), \1\nbltzl \$\w+, [^\n]+\nadd\.d \1, \1, (\$f\d+)\n'
    r'(?:(?:addiu|addu|sll|move|lw|lui|nop)\b[^\n]*\n){0,8}cvt\.s\.d \1, \1'
)
_LOOP = re.compile(
    rf'(?P<indent>^[ \t]+)(?P<setup>{IDENT}\s*=\s*{IDENT};\s*do\s*\{{\s*do\s*\{{\s*'
    rf'u32\s+(?P<word>{IDENT})\s*=\s*{IDENT}\[{IDENT}\s*\+\s*{IDENT}\];\s*)',
    re.M,
)
_COMPONENT = re.compile(
    rf'(?P<dest>{IDENT})\[(?P<index>[012])\]\s*=\s*\(f32\)\s*\(\(f64\)\s*'
    rf'\((?P<expr>\((?P<word>{IDENT})\s*(?:>>|<<)\s*\d+\)\s*(?:\*|&)\s*(?:0x[\da-fA-F]+|\d+)U)\)\)\s*;\s*'
)


def variants(source, name, header, rows, read_data, big_endian):
    if not read_data:
        return []
    rows = list(rows)
    pools = {hit.groups() for kind, target, candidate in rows if kind != ' ' and '?local' in candidate
             and (hit := _POOL.fullmatch(target))}
    if len(pools) != 1:
        return []
    reg, symbol = pools.pop()
    target = '\n'.join(left for _, left, _ in rows if left)
    if sum(match[2] == reg for match in _CONVERSION.finditer(target)) != 3:
        return []
    if read_data(symbol, 8) != struct.pack('>d' if big_endian else '<d', 4294967296.0):
        return []
    part = view(source, name)
    declarations = header + '\n' + source
    if not part or re.search(rf'\b(?:{symbol}|repair_unsigned_float|repair_conversion_bias)\b', declarations):
        return []
    matches = []
    for loop in _LOOP.finditer(part.clean, part.opening, part.end):
        pos = loop.end()
        components = []
        for index in range(3):
            match = _COMPONENT.match(part.clean, pos, part.end)
            if not match or match['word'] != loop['word'] or int(match['index']) != index:
                break
            components.append(match)
            pos = match.end()
        if len(components) == 3 and len({match['dest'] for match in components}) == 1:
            matches.append((loop, components))
    if len(matches) != 1:
        return []
    loop, components = matches[0]
    names = {loop['word'], components[0]['dest'], 'u32', 's32', 'f32', 'f64'}
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({IDENT})', declarations))
    if names & macros:
        return []
    rewritten = [(loop.start(), loop.start(), f"{loop['indent']}f64 repair_conversion_bias = {symbol};\n")]
    for match in components:
        begin, end = match.span()
        original = source[begin:end]
        if '/*' in original or '//' in original:
            return []
        expr = source[slice(*match.span('expr'))]
        replacement = (f"{match['dest']}[{match['index']}] = "
                       f"repair_unsigned_float({expr}, repair_conversion_bias);")
        rewritten.append((begin, end, replacement + original[len(original.rstrip()):]))
    helper = (
        f'extern const f64 {symbol};\n'
        'static inline f32 repair_unsigned_float(u32 x, f64 bias) {\n'
        '    f64 result = (s32)x;\n'
        '    if ((s32)x < 0) result += bias;\n'
        '    return (f32)result;\n'
        '}\n'
    )
    return [(FAMILY, helper + edit(source, rewritten))]
