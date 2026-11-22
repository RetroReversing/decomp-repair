"""Recover a measured indexed two-mode selection and direct return."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lui \$v0, %hi\((?P<global>{IDENT})\)\nlw \$v0, %lo\((?P=global)\)\(\$v0\)\n'
    r'andi \$a0, \$a0, 0xff\nsll \$v1, \$a0, 2\naddu \$v1, \$v1, \$a0\nsll \$v1, \$v1, 2\n'
    r'sw \$ra, [^\n]+\naddu \$v1, \$v0, \$v1\n'
    rf'lw \$v0, (?P<first>{NUM})\(\$v1\)\nbne \$a1, \$v0, [^\n]+\nnop\n'
    rf'j [^\n]+\nlui \$a1, (?P<mode1>{NUM})\nlw \$v0, (?P<second>{NUM})\(\$v1\)\n'
    rf'bne \$a1, \$v0, [^\n]+\nmove \$v0, \$zero\nlui \$a1, (?P<mode2>{NUM})\n'
    rf'jal (?P<callee>{IDENT})\nnop\nsll \$v0, \$v0, 0x18'
)
CANDIDATE = re.compile(
    rf'lui \$v1, %hi\((?P<global>{IDENT})\)\nlw \$v1, %lo\((?P=global)\)\(\$v1\)\n'
    r'andi \$a0, \$a0, 0xff\nsll \$v0, \$a0, 2\naddu \$v0, \$v0, \$a0\nsll \$v0, \$v0, 2'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or t['global'] != c['global']:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    signature = re.search(rf'\bs8\s+{re.escape(name)}\s*\(\s*s32\s+(?P<indexarg>{IDENT})\s*,\s*'
                          rf's32\s+(?P<key>{IDENT})\s*\)', part.clean[:part.opening])
    if not signature:
        return []
    pattern = re.compile(
        rf'(?P<index>{IDENT})\s*=\s*{re.escape(signature["indexarg"])}\s*&\s*0[xX]FF\s*;\s*'
        rf'(?P<entry>{IDENT})\s*=\s*\(void\s*\*\)\s*\(\s*{re.escape(t["global"])}\s*\)\s*;\s*'
        rf'(?P=entry)\s*=\s*\(void\s*\*\)\s*\(\s*\(char\s*\*\)\s*(?P=entry)\s*\+\s*'
        rf'\(s32\)\s*\(\s*\(\s*(?P=index)\s*\*\s*(?P<stride>{NUM})\s*\)\s*\)\s*\)\s*;\s*'
        rf'if\s*\(\s*{re.escape(signature["key"])}\s*==\s*M2C_FIELD\(\s*(?P=entry)\s*,\s*s32\s*\*\s*,\s*'
        rf'(?P<first>{NUM})\s*\)\s*\)\s*{{\s*(?P<mode>{IDENT})\s*=\s*(?P<mode1>{NUM})\s*;\s*'
        rf'goto\s+(?P<label>{IDENT})\s*;\s*}}\s*(?P<result>{IDENT})\s*=\s*0\s*;\s*'
        rf'if\s*\(\s*{re.escape(signature["key"])}\s*==\s*M2C_FIELD\(\s*(?P=entry)\s*,\s*s32\s*\*\s*,\s*'
        rf'(?P<second>{NUM})\s*\)\s*\)\s*{{\s*(?P=mode)\s*=\s*(?P<mode2>{NUM})\s*;\s*'
        rf'(?P=label)\s*:\s*(?P=result)\s*=\s*{re.escape(t["callee"])}\(\s*(?P=index)\s*,\s*(?P=mode)\s*\)\s*;\s*}}\s*'
        rf'return\s+(?P=result)\s*;'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if (int(m['stride'], 0) != 20 or any(int(m[k], 0) != int(t[k], 0) for k in ('first', 'second'))
            or any(int(m[k], 0) != int(t[k], 0) << 16 for k in ('mode1', 'mode2'))):
        return []
    if len(re.findall(rf'\b{re.escape(m["label"])}\b', part.body)) != 2:
        return []
    if len({signature['indexarg'], signature['key'], m['index'], m['entry'], m['mode'], m['result']}) != 6:
        return []
    for typ, key, n in (('s32', 'index', 4), ('void\\s*\\*', 'entry', 6), ('M2C_UNK', 'mode', 4),
                        ('s8', 'result', 4)):
        if not re.search(rf'\b{typ}\s*{re.escape(m[key])}\s*;', part.body):
            return []
        if len(re.findall(rf'\b{re.escape(m[key])}\b', part.body)) != n:
            return []
    if not re.search(rf'\bextern\s+s32\s+{re.escape(t["global"])}\s*;', part.clean[:part.opening]):
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(x)}\b', source + '\n' + header)
           for x in (t['global'], signature['indexarg'], signature['key'], m['index'], m['entry'], m['mode'])):
        return []
    tmp = '__repair_index_base'
    if re.search(rf'\b{tmp}\b', source + '\n' + header):
        return []
    original = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    idx, entry, mode, key = m['index'], m['entry'], m['mode'], signature['key']
    replacement = (f'{tmp} = (void *){t["global"]};\n    {idx} = {signature["indexarg"]} & 0xFF;\n'
                   f'    {entry} = (void *)((char *){tmp} + {idx} * {m["stride"]});\n'
                   f'    if ({key} == M2C_FIELD({entry}, s32 *, {m["first"]})) {{\n'
                   f'        {mode} = {m["mode1"]};\n'
                   f'    }} else if ({key} == M2C_FIELD({entry}, s32 *, {m["second"]})) {{\n'
                   f'        {mode} = {m["mode2"]};\n    }} else {{\n        return 0;\n    }}\n'
                   f'    return {t["callee"]}({idx}, {mode});')
    return [('measured_indexed_mode_tail', edit(source, [
        (part.opening + 1, part.opening + 1, f'\n    void *{tmp};'),
        (part.opening + 1 + m.start(), part.opening + 1 + m.end(), replacement),
    ]))]
