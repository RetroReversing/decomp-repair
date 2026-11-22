"""Recover a missing owner argument in a guarded lookup."""

import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lw \$v0, (?P<outer>{NUM})\(\$s0\)\nlw \$v0, (?P<inner>{NUM})\(\$v0\)\n'
    rf'beqz \$v0, [^\n]+\nnop\njal (?P<callee>{IDENT})\nmove \$a1, \$v0'
)
CANDIDATE = re.compile(
    rf'lw \$v0, (?P<outer>{NUM})\(\$s0\)\nlw \$a0, (?P<inner>{NUM})\(\$v0\)\n'
    rf'beqz \$a0, [^\n]+\nnop\njal (?P<callee>{IDENT})\nnop'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if (not t or not c or any(t[k] != c[k] for k in ('outer', 'inner', 'callee'))
            or 'move $s0, $a0' not in target or 'move $s0, $a0' not in candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    callee = t['callee']
    if re.search(rf'\b{re.escape(callee)}\b', header) or len(re.findall(rf'\b{re.escape(callee)}\b', part.clean)) != 2:
        return []
    proto = re.search(rf'\bvoid\s*\*\s*{re.escape(callee)}\s*\(\s*s32\s*\)\s*;', part.clean[:part.opening])
    if not proto:
        return []
    pattern = re.compile(
        rf'(?P<first>{IDENT})\s*=\s*M2C_FIELD\(\s*M2C_FIELD\(\s*(?P<owner>{IDENT})\s*,\s*'
        rf'void\s*\*\*\s*,\s*(?P<outer>{NUM})\s*\)\s*,\s*s32\s*\*\s*,\s*(?P<inner>{NUM})\s*\)\s*;\s*'
        rf'if\s*\(\s*(?P=first)\s*!=\s*0\s*\)\s*{{\s*(?P<second>{IDENT})\s*=\s*'
        rf'{re.escape(callee)}\(\s*(?P=first)\s*\)\s*;\s*if\s*\(\s*(?P=second)\s*!=\s*NULL\s*\)\s*{{'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if any(int(m[k], 0) != int(t[k], 0) for k in ('outer', 'inner')):
        return []
    first, second, owner = m['first'], m['second'], m['owner']
    if len({first, second, owner}) != 3:
        return []
    sig = re.search(rf'\bvoid\s*\*\s*{re.escape(owner)}\b', part.clean[:part.opening])
    d1 = re.search(rf'\bs32\s+{re.escape(first)}\s*;', part.body)
    d2 = re.search(rf'\bvoid\s*\*\s*{re.escape(second)}\s*;', part.body)
    if not sig or not d1 or not d2:
        return []
    if len(re.findall(rf'\b{re.escape(first)}\b', part.body)) != 4:
        return []
    refs = list(re.finditer(rf'\b{re.escape(second)}\b', part.body))
    inner_end = close(part.clean, part.opening + m.end(), '{', '}')
    if (len(refs) != 4 or sum(h.start() >= m.end() for h in refs) != 1 or not inner_end
            or any(part.opening + 1 + h.start() >= inner_end for h in refs)):
        return []
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{re.escape(first)}|{re.escape(second)}|{re.escape(owner)})\b',
                 source + '\n' + header):
        return []
    old = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    if '/*' in old or '//' in old:
        return []
    replacement = (f'{first} = M2C_FIELD(M2C_FIELD({owner}, void **, {m["outer"]}), void **, {m["inner"]});\n'
                   f'    if ({first} != NULL) {{\n        {first} = {callee}({owner}, {first});\n'
                   f'        if ({first} != NULL) {{')
    start = part.opening + 1
    edits = [(proto.start(), proto.end(), f'void *{callee}(void *, void *);'),
             (start + d1.start(), start + d1.end(), f'void *{first};'),
             (start + d2.start(), start + d2.end(), ''),
             (start + m.start(), start + m.end(), replacement)]
    edits += [(start + h.start(), start + h.end(), first) for h in refs if h.start() >= m.end()]
    return [('measured_lookup_owner', edit(source, edits))]
