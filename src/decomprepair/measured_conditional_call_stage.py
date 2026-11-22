"""Stage a conditional global read and a later call's owner argument."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lui \$v0, %hi\((?P<slot>{IDENT})\)\nlw \$v0, %lo\((?P=slot)\)\(\$v0\)\n'
    rf'lui \$v1, %hi\((?P<cond>{IDENT})\)\nlw \$v1, %lo\((?P=cond)\)\(\$v1\)\n'
    rf'sh \$zero, (?P<field>{NUM})\(\$v0\)\nlh \$v1, (?P<test>{NUM})\(\$v1\)'
)
CANDIDATE = re.compile(
    rf'lui \$v0, %hi\((?P<slot>{IDENT})\)\nlw \$v0, %lo\((?P=slot)\)\(\$v0\)\n'
    rf'sh \$zero, (?P<field>{NUM})\(\$v0\)\nlui \$v0, %hi\((?P<cond>{IDENT})\)\n'
    rf'lw \$v0, %lo\((?P=cond)\)\(\$v0\)\nlh \$v1, (?P<test>{NUM})\(\$v0\)'
)
CALL_T = re.compile(rf'move \$a0, \$s0\naddiu \$a1, \$zero, (?P<value>{NUM})\njal (?P<callee>{IDENT})\nnop')
CALL_C = re.compile(rf'addiu \$a1, \$zero, (?P<value>{NUM})\njal (?P<callee>{IDENT})\nmove \$a0, \$s0')


def variants(source, name, header, rows, *, resolve=None):
    if resolve is None:
        return []
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c, ct, cc = TARGET.search(target), CANDIDATE.search(candidate), CALL_T.search(target), CALL_C.search(candidate)
    if not all((t, c, ct, cc)):
        return []
    if (any(t[k] != c[k] for k in ('slot', 'cond', 'field', 'test'))
            or any(ct[k] != cc[k] for k in ('value', 'callee'))):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean):
        return []
    pattern = re.compile(
        rf'(?P<first>M2C_FIELD\(\s*{IDENT}\s*,\s*s8\s*\*\s*,\s*{NUM}\s*\)\s*=\s*1\s*;)\s*'
        rf'M2C_FIELD\(\s*M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*void\s*\*\*\s*,\s*'
        rf'(?P<slot>{NUM})\s*\)\s*,\s*u16\s*\*\s*,\s*(?P<field>{NUM})\s*\)\s*=\s*0U?\s*;\s*'
        rf'if\s*\(\s*M2C_FIELD\(\s*(?P<condition>M2C_FIELD\(\s*&\s*(?P=base)\s*,\s*'
        rf'void\s*\*\*\s*,\s*(?P<cond>{NUM})\s*\))\s*,\s*s16\s*\*\s*,\s*(?P<test>{NUM})\s*\)\s*'
        rf'==\s*{NUM}\s*\)\s*{{\s*(?P<choice>{IDENT})\s*=\s*{NUM}\s*;\s*}}\s*else\s*{{'
        rf'(?P<elsebody>[^{{}}]*?)\b(?P=choice)\s*=\s*(?P<value>{NUM})\s*;\s*}}\s*'
        rf'{re.escape(ct["callee"])}\(\s*(?P<owner>{IDENT})\s*,\s*(?P=choice)\s*\)\s*;'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if any(int(m[k], 0) != int(t[k], 0) for k in ('field', 'test')) or int(m['value'], 0) != int(ct['value'], 0):
        return []
    base = resolve(m['base'])
    if (base is None or resolve(t['slot']) != base + int(m['slot'], 0)
            or resolve(t['cond']) != base + int(m['cond'], 0)):
        return []
    if not re.search(rf'\bs32\s+{re.escape(m["owner"])}\b', part.clean[:part.opening]):
        return []
    if not re.search(rf'\b(?:s32|M2C_UNK)\s+{re.escape(m["choice"])}\s*;', part.body):
        return []
    if not re.search(r'\b' + IDENT + r'\s*\(', m['elsebody']):
        return []
    tmp_ptr, tmp_owner = '__repair_condition_owner', '__repair_call_owner'
    if any(re.search(rf'\b{re.escape(x)}\b', source + '\n' + header) for x in (tmp_ptr, tmp_owner)):
        return []
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{re.escape(m["base"])}|{re.escape(m["owner"])}|'
                 rf'{re.escape(m["choice"])})\b', source + '\n' + header):
        return []
    original = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    # Retain the original relative order of all stores and calls; the target
    # shows the condition pointer loaded before the guarded store.
    return [('measured_conditional_call_stage', edit(source, [
        (start, start, f'\n    void *{tmp_ptr};\n    s32 {tmp_owner};'),
        (start + m.start('first'), start + m.start('first'), f'{tmp_owner} = {m["owner"]};\n    '),
        (start + m.end('first'), start + m.end('first'), f'\n    {tmp_ptr} = {m["condition"]};'),
        (start + m.start('condition'), start + m.end('condition'), tmp_ptr),
        (start + m.end('elsebody'), start + m.end('elsebody'), f'{tmp_owner} = {m["owner"]};\n        '),
        (start + m.start('owner'), start + m.end('owner'), tmp_owner),
    ]))]
