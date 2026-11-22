"""Recover the measured write-before-read order for a record pointer update."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lui \$a0, %hi\((?P<global>{IDENT})\)\nlw \$a0, %lo\((?P=global)\)\(\$a0\)\n'
    rf'sw \$s0, (?P<slot>{NUM})\(\$a0\)\nlw \$a1, (?P=slot)\(\$a0\)\n'
    rf'addiu \$v1, \$zero, (?P<flagvalue>{NUM})\nsh \$v1, (?P<flag>{NUM})?\(\$a0\)\n'
    rf'lw \$v1, (?P<src>{NUM})\(\$a1\)\nsw \$v1, (?P<dest>{NUM})\(\$a0\)\n'
    rf'jal (?P<restore>{IDENT})\nmove \$a0, \$v0'
)
CANDIDATE = re.compile(
    rf'lui \$a0, %hi\((?P<global>{IDENT})\)\nlw \$a0, %lo\((?P=global)\)\(\$a0\)\n'
    rf'lw \$a1, (?P<slot>{NUM})\(\$a0\)\nsw \$s0, (?P=slot)\(\$a0\)\n'
    rf'lw \$a2, (?P<src>{NUM})\(\$a1\)\naddiu \$v1, \$zero, (?P<flagvalue>{NUM})\n'
    rf'sh \$v1, (?P<flag>{NUM})?\(\$a0\)\nsw \$a2, (?P<dest>{NUM})\(\$a0\)'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or any(t[k] != c[k] for k in ('global', 'slot', 'src', 'dest', 'flag', 'flagvalue')):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    pattern = re.compile(
        rf'(?P<read>(?P<tmp>{IDENT})\s*=\s*\(\(\s*(?P<type>__repair_record_{IDENT})\s*\*\s*\)\s*'
        rf'(?P<global>{IDENT})\s*\)\s*->\s*field_(?P<slot>[0-9a-fA-F]+)\s*;)\s*'
        rf'(?P<write>\(\(\s*(?P=type)\s*\*\s*\)\s*(?P=global)\s*\)\s*->\s*field_(?P=slot)\s*=\s*(?P<owner>{IDENT})\s*;)\s*'
        rf'(?P<copy>\(\(\s*(?P=type)\s*\*\s*\)\s*(?P=global)\s*\)\s*->\s*field_(?P<dest>[0-9a-fA-F]+)\s*=\s*'
        rf'\(s32\)\s*M2C_FIELD\(\s*(?P=tmp)\s*,\s*s32\s*\*\s*,\s*(?P<src>{NUM})\s*\)\s*;)\s*'
        rf'(?P<flag>\(\(\s*(?P=type)\s*\*\s*\)\s*(?P=global)\s*\)\s*->\s*field_(?P<flagoff>[0-9a-fA-F]+)\s*=\s*'
        rf'(?P<flagvalue>{NUM})\s*;)\s*'
        rf'{re.escape(t["restore"])}\(\s*{IDENT}\s*,\s*(?P=tmp)\s*\)\s*;'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if (m['global'] != t['global'] or int(m['slot'], 16) != int(t['slot'], 0)
            or int(m['dest'], 16) != int(t['dest'], 0) or int(m['src'], 0) != int(t['src'], 0)
            or int(m['flagoff'], 16) != int(t['flag'] or '0', 0)
            or int(m['flagvalue'], 0) != int(t['flagvalue'], 0)):
        return []
    if len({int(m['slot'], 16), int(m['dest'], 16), int(m['flagoff'], 16)}) != 3:
        return []
    if not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(m["global"])}\s*;', part.clean[:part.opening]):
        return []
    if not re.search(rf'\bvoid\s*\*\s*{re.escape(m["tmp"])}\s*;', part.body):
        return []
    if not re.search(rf'\bvoid\s*\*\s*{re.escape(m["owner"])}\b', part.clean[:part.opening]):
        return []
    if len(re.findall(rf'\b{re.escape(m["tmp"])}\b', part.body)) != 4:
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(m[k])}\b', source + '\n' + header)
           for k in ('tmp', 'owner', 'global')):
        return []
    start = part.opening + 1
    original = source[start + m.start('read'):start + m.end('flag')]
    line_start = source.rfind('\n', 0, start + m.start('read')) + 1
    original = source[line_start:start + m.start('read')] + original
    if '/*' in original or '//' in original or '#' in original:
        return []
    statements = [source[start + m.start(k):start + m.end(k)] for k in ('write', 'flag', 'read', 'copy')]
    return [('measured_record_pointer_update', edit(source, [(start + m.start('read'), start + m.end('flag'),
                                                               '\n    '.join(statements))]))]
