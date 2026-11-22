"""Widen a measured word argument split across four byte stores."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    M2C_FIELD(@dst, s8 *, @offeight) = (s8) (@value >> 8);
    M2C_FIELD(@dst, u8 *, @offzero) = @value;
    M2C_FIELD(@dst, s8 *, @offsixteen) = (s8) (@value >> 0x10);
    M2C_FIELD(@dst, s8 *, @offtwentyfour) = (s8) (@value >> 0x18);
''', numbers=('offeight', 'offzero', 'offsixteen', 'offtwentyfour'))

TARGET = re.compile(
    r'srl \$v0, \$a0, 8\nsb \$v0, (?P<eight>\d*)\(\$a1\)\n'
    r'srl \$v0, \$a0, 16\nsb \$a0, (?P<zero>\d*)\(\$a1\)\n'
    r'srl \$a0, \$a0, 24\nsb \$v0, (?P<sixteen>\d*)\(\$a1\)\n'
    r'jr \$ra\nsb \$a0, (?P<twentyfour>\d*)\(\$a1\)'
)


def variants(source, name, header, rows):
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    measured = TARGET.search(target)
    part = view(source, name)
    if not measured or not part:
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m or m['value'] == m['dst']:
        return []
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*(?P<type>u8)\s+{m["value"]}\s*,\s*'
                          rf'void\s*\*\s*{m["dst"]}\s*\)\s*$', part.clean[:part.opening])
    if not signature:
        return []
    # A conflicting declaration or macro elsewhere cannot be updated here.
    outside = part.clean[:signature.start()] + part.clean[part.end:] + '\n' + _blank(header)
    if re.search(rf'\b{re.escape(name)}\s*\(', outside):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection((m['value'], m['dst'], name)):
        return []
    for suffix in ('eight', 'zero', 'sixteen', 'twentyfour'):
        if integer(m['off' + suffix]) != int(measured[suffix] or '0'):
            return []
    return [('measured_word_byte_packing', edit(source, [(*signature.span('type'), 'u32')]))]
