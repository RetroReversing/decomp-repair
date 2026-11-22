"""Keep a measured global flag owner across a shared conditional update."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<symbol>{IDENT})\)\nlw \$v1, %lo\((?P=symbol)\)\(\$v1\)\n'
    rf'lhu \$v0, (?P<field>{NUM})\(\$v1\)'
)
TARGET_STORE = re.compile(rf'andi \$v0, \$v0, {NUM}\nsh \$v0, (?P<field>{NUM})\(\$v1\)')
CANDIDATE_STORE = re.compile(
    rf'andi \$v1, \$v0, {NUM}\nlui \$v0, %hi\((?P<symbol>{IDENT})\)\n'
    rf'lw \$v0, %lo\((?P=symbol)\)\(\$v0\)\nsh \$v1, (?P<field>{NUM})\(\$v0\)'
)


def variants(source, name, header, rows, *, resolve=None):
    if resolve is None:
        return []
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    loads = list(TARGET.finditer(target))
    t, c = TARGET_STORE.search(target), CANDIDATE_STORE.search(candidate)
    if (len(loads) != 2 or not t or not c or loads[0]['symbol'] != loads[1]['symbol']
            or c['symbol'] != loads[0]['symbol'] or any(x['field'] != t['field'] for x in (*loads, c))):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    expr = re.compile(rf'M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*void\s*\*\*\s*,\s*'
                      rf'(?P<offset>{NUM})\s*\)')
    hits = list(expr.finditer(part.body))
    if len(hits) != 4 or len({(m['base'], m['offset']) for m in hits}) != 1:
        return []
    base, displacement = hits[0]['base'], int(hits[0]['offset'], 0)
    origin, address = resolve(base), resolve(loads[0]['symbol'])
    if origin is None or address is None or origin + displacement != address:
        return []
    outer = re.search(rf'if\s*\(\s*{IDENT}\s*!=\s*0\s*\)\s*{{', part.body)
    guard = re.search(rf'if\s*\(\s*M2C_FIELD\(\s*{re.escape(hits[0][0])}\s*,\s*u16\s*\*\s*,\s*'
                      rf'(?P<field>{NUM})\s*\)\s*&\s*{NUM}\s*\)\s*{{', part.body)
    if not outer or not guard or not (outer.end() < hits[0].start() < guard.start()):
        return []
    if int(guard['field'], 0) != int(t['field'], 0):
        return []
    if len(re.findall(r'\bgoto\s+' + IDENT + r'\s*;', part.body)) != 1:
        return []
    if not re.search(r'\b' + IDENT + r'\s*:\s*M2C_FIELD\(', part.body):
        return []
    tmp = '__repair_flag_owner'
    if re.search(rf'\b{tmp}\b', source + '\n' + header):
        return []
    if re.search(rf'(?m)^\s*#\s*define\s+{re.escape(base)}\b', source + '\n' + header):
        return []
    start = part.opening + 1
    edits = [(start, start, f'\n    void *{tmp};'),
             (start + outer.end(), start + outer.end(), f'\n        {tmp} = {hits[0][0]};'),
             (start + guard.start(), start + guard.start(), f'{tmp} = {hits[0][0]};\n    ')]
    edits.extend((start + h.start(), start + h.end(), tmp) for h in hits)
    return [('measured_conditional_flag_owner', edit(source, edits))]
