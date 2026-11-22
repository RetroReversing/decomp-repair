"""Recover measured shared state in a guarded list allocation."""

import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lw \$s0, (?P<first>{NUM})\(\$v0\)\nmove \$a2, \$a0\nbnez \$s0, [^\n]+\nmove \$s1, \$zero\n'
    rf'lw \$s0, (?P<second>{NUM})\(\$v0\)\nbeqz \$s0, [^\n]+\nnop\nmove \$a0, \$s0\n'
    rf'jal (?P<unlink>{IDENT})\nsw \$s0, \(\$a2\)\n'
    rf'lui \$a1, %hi\((?P<global>{IDENT})\)\nlw \$a1, %lo\((?P=global)\)\(\$a1\)\n'
    rf'move \$a0, \$s0\njal (?P<link>{IDENT})\naddiu \$a1, \$a1, (?P<linkoff>{NUM})\n'
    r'j [^\n]+\nmove \$v0, \$s1'
)
CANDIDATE = re.compile(
    rf'lw \$s0, (?P<first>{NUM})\(\$v0\)\nmove \$s1, \$a0\nbnez \$s0, [^\n]+\nmove \$a2, \$zero\n'
    rf'lw \$s0, (?P<second>{NUM})\(\$v0\)\nbeqz \$s0, [^\n]+\nnop\nmove \$a0, \$s0\n'
    rf'jal (?P<unlink>{IDENT})\nmove \$a1, \$s1\nsw \$s0, \(\$s1\)'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or any(t[k] != c[k] for k in ('first', 'second', 'unlink')):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    part.end = end
    unlink = t['unlink']
    if re.search(rf'\b{re.escape(unlink)}\b', header) or len(re.findall(rf'\b{re.escape(unlink)}\b', part.clean)) != 2:
        return []
    proto = re.search(rf'\bM2C_UNK\s+{re.escape(unlink)}\s*\(\s*void\s*\*\s*,\s*void\s*\*\*\s*\)\s*;',
                      part.clean[:part.opening])
    if not proto:
        return []
    sig = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*void\s*\*\*\s*(?P<out>{IDENT})\s*,\s*'
                    rf's16\s+(?P<priority>{IDENT})\s*\)', part.clean[:part.opening])
    if not sig:
        return []
    pattern = re.compile(
        rf'(?P<cursor>{IDENT})\s*=\s*M2C_FIELD\(\s*{re.escape(t["global"])}\s*,\s*void\s*\*\*\s*,\s*'
        rf'(?P<first>{NUM})\s*\)\s*;\s*(?P<success>{IDENT})\s*=\s*0\s*;\s*'
        rf'if\s*\(\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*\|\|\s*'
        rf'\(\s*(?P=cursor)\s*=\s*M2C_FIELD\(\s*{re.escape(t["global"])}\s*,\s*void\s*\*\*\s*,\s*'
        rf'(?P<second>{NUM})\s*\)\s*,\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*\)\s*\)\s*{{\s*'
        rf'{re.escape(unlink)}\(\s*(?P=cursor)\s*,\s*{re.escape(sig["out"])}\s*\)\s*;\s*'
        rf'\*\s*{re.escape(sig["out"])}\s*=\s*(?P=cursor)\s*;\s*'
        rf'{re.escape(t["link"])}\(\s*(?P=cursor)\s*,\s*{re.escape(t["global"])}\s*\+\s*(?P<linkoff>{NUM})\s*\)\s*;\s*'
        rf'return\s+0\s*;\s*}}\s*'
        rf'(?P<slow>{IDENT})\s*=\s*M2C_FIELD\(\s*{re.escape(t["global"])}\s*,\s*void\s*\*\*\s*,\s*{NUM}\s*\)\s*;\s*'
        rf'(?P<result>{IDENT})\s*=\s*0\s*;\s*if\s*\(\s*(?P=slow)\s*!=\s*NULL\s*\)\s*{{'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if any(int(m[k], 0) != int(t[k], 0) for k in ('first', 'second', 'linkoff')):
        return []
    cursor, slow, success, result, out = m['cursor'], m['slow'], m['success'], m['result'], sig['out']
    if len({cursor, slow, success, result, out, sig['priority']}) != 6:
        return []
    for typ, variable in (('void\\s*\\*', cursor), ('void\\s*\\*', slow), ('s32', success), ('s32', result)):
        if not re.search(rf'\b{typ}\s*{re.escape(variable)}\s*;', part.body):
            return []
    slow_decl = re.search(rf'\bvoid\s*\*\s*{re.escape(slow)}\s*;', part.body)
    if not slow_decl:
        return []
    # The result is zero for the fast/empty paths and mirrors success on every
    # slow iteration; no other writes to either scalar may be hidden here.
    if len(re.findall(rf'\b{re.escape(result)}\b', part.body)) != 4:
        return []
    if len(re.findall(rf'\b{re.escape(success)}\b', part.body)) != 4:
        return []
    if (not re.search(rf'\b{re.escape(result)}\s*=\s*{re.escape(success)}\s*;\s*}}\s*'
                      rf'while\s*\(\s*{re.escape(slow)}\s*!=\s*NULL\s*\)\s*;\s*}}\s*'
                      rf'return\s+{re.escape(result)}\s*;', part.body[m.end():])
            or not re.search(rf'\b{re.escape(success)}\s*=\s*1\s*;', part.body[m.end():])):
        return []
    if len(re.findall(rf'\b{re.escape(cursor)}\b', part.body)) != 8:
        return []
    if any(h.start() < m.end() for h in re.finditer(rf'\b{re.escape(slow)}\b', part.body)
           if not (slow_decl.start() <= h.start() < slow_decl.end()) and h.start() < m.start()):
        return []
    tail = re.search(rf'\breturn\s+{re.escape(result)}\s*;\s*$', part.body)
    if not tail or tail.start() <= m.end():
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(x)}\b', source + '\n' + header)
           for x in (cursor, slow, success, result, out, unlink, t['link'])):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    body_text = source[start:part.end - 1]
    replacement = body_text
    fast = (f'{unlink}({cursor}, {out});\n        *{out} = {cursor};\n'
            f'        {t["link"]}({cursor}, {t["global"]} + {m["linkoff"]});\n        return 0;\n    }}')
    new_fast = (f'*{out} = {cursor};\n        {unlink}({cursor});\n'
                f'        {t["link"]}({cursor}, {t["global"]} + {m["linkoff"]});\n    }} else {{')
    if fast not in replacement:
        return []
    replacement = replacement.replace(fast, new_fast, 1)
    replacement = re.sub(rf'\bvoid\s*\*\s*{re.escape(slow)}\s*;', '', replacement, count=1)
    replacement = re.sub(rf'\b{re.escape(slow)}\b', cursor, replacement)
    replacement = re.sub(rf'\breturn\s+{re.escape(result)}\s*;\s*$', f'}}\n    return {success};\n', replacement)
    return [('measured_two_list_allocation', edit(source, [
        (proto.start(), proto.end(), f'M2C_UNK {unlink}(void *);'),
        (start, part.end - 1, replacement),
    ]))]
