"""Stage a measured clock load before an independent parameter delay load."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lw \$v0, (?P<unit>{NUM})\(\$s1\)\nlw \$v1, (?P<clock>{NUM})\(\$a0\)\n'
    rf'lw \$a2, (?P<delay>{NUM})\(\$v0\)\nmove \$a1, \$s3\n'
    rf'addiu \$v0, \$zero, (?P<kind>{NUM})\nsh \$v0, (?P<field>{NUM})\(\$s0\)'
)
CANDIDATE = re.compile(
    rf'lw \$v0, (?P<unit>{NUM})\(\$s1\)\nlw \$a2, (?P<delay>{NUM})\(\$v0\)\n'
    rf'move \$a1, \$s3\naddiu \$v0, \$zero, (?P<kind>{NUM})\nsh \$v0, (?P<field>{NUM})\(\$s0\)\n'
    rf'lw \$v1, (?P<clock>{NUM})\(\$a0\)'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or any(int(t[k], 0) != int(c[k], 0) for k in ('unit', 'clock', 'delay', 'kind', 'field')):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    pattern = re.compile(
        rf'(?P<delayvar>{IDENT})\s*=\s*M2C_FIELD\(\s*M2C_FIELD\(\s*(?P<voice>{IDENT})\s*,\s*'
        rf'void\s*\*\*\s*,\s*(?P<unit>{NUM})\s*\)\s*,\s*s32\s*\*\s*,\s*(?P<delay>{NUM})\s*\)\s*;\s*'
        rf'M2C_FIELD\(\s*(?P<param>{IDENT})\s*,\s*s16\s*\*\s*,\s*(?P<field>{NUM})\s*\)\s*=\s*(?P<kind>{NUM})\s*;\s*'
        rf'M2C_FIELD\(\s*(?P=param)\s*,\s*s32\s*\*\s*,\s*{NUM}\s*\)\s*=\s*\(s32\)\s*\(\s*'
        rf'(?P<read>M2C_FIELD\(\s*(?P<owner>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<clock>{NUM})\s*\))\s*'
        rf'\+\s*(?P=delayvar)\s*\)\s*;'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if any(int(m[k], 0) != int(t[k], 0) for k in ('unit', 'clock', 'delay', 'kind', 'field')):
        return []
    if len({m['voice'], m['owner'], m['param'], m['delayvar']}) != 4:
        return []
    if not re.search(rf'\bs32\s+{re.escape(m["delayvar"])}\s*;', part.body):
        return []
    signature = part.clean[:part.opening]
    if any(not re.search(rf'\bvoid\s*\*\s*{re.escape(m[k])}\b', signature) for k in ('voice', 'owner')):
        return []
    tmp = '__repair_clock'
    if re.search(rf'\b{tmp}\b', source + '\n' + header):
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(m[x])}\b', source + '\n' + header)
           for x in ('voice', 'owner', 'param', 'delayvar')):
        return []
    original = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    return [('measured_parameter_clock_load', edit(source, [
        (start, start, f'\n    s32 {tmp};'),
        (start + m.start(), start + m.start(), f'{tmp} = {m["read"]};\n            '),
        (start + m.start('read'), start + m.end('read'), tmp),
    ]))]
