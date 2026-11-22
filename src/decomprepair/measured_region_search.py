"""Restore a measured region search's ordered bounds checks."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
FIELD = r'M2C_FIELD\s*\(\s*{obj}\s*,\s*{kind}\s*\*\s*,\s*{off}\s*\)'


def field(obj, kind, off):
    return FIELD.format(obj=obj, kind=kind, off=off)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    if not re.search(r'lw \$a3, \(\$a1\)\nlw \$v0, (?:0x[0-9a-f]+|[0-9]+)\(\$a2\)\n'
                     r'slt \$v0, \$a3, \$v0', target):
        return []
    if not re.search(r'lw \$v0, (?:0x[0-9a-f]+|[0-9]+)\(\$a2\)\n'
                     r'lw \$v1, 8\(\$a1\)\nslt \$v0, \$v1, \$v0', target):
        return []
    part = view(source, name)
    if not part:
        return []
    pattern = re.compile(
        rf'\s*s32\s+(?P<x>{IDENT})\s*;\s*s32\s+(?P<y>{IDENT})\s*;\s*'
        rf'void\s*\*\s*(?P<cursor>{IDENT})\s*;\s*void\s*\*\s*(?P<result>{IDENT})\s*;\s*'
        rf'(?P=cursor)\s*=\s*(?P<head>{IDENT})\s*;\s*(?P=x)\s*=\s*'
        rf'{field("(?P<point>" + IDENT + ")", "s32", "0")}\s*;\s*'
        rf'(?P<label>{IDENT})\s*:\s*if\s*\(\s*\(\s*(?P=x)\s*<\s*'
        rf'{field("(?P=cursor)", "s32", "(?P<xmin>" + NUM + ")")}\s*\)\s*\|\|\s*\(\s*'
        rf'{field("(?P=cursor)", "s32", "(?P<xmax>" + NUM + ")")}\s*<\s*(?P=x)\s*\)\s*\|\|\s*\(\s*'
        rf'(?P=y)\s*=\s*{field("(?P=point)", "s32", "8")}\s*,\s*\(\s*\(\s*(?P=y)\s*<\s*'
        rf'{field("(?P=cursor)", "s32", "(?P<ymin>" + NUM + ")")}\s*\)\s*!=\s*0\s*\)\s*\)\s*\|\|\s*'
        rf'\(\s*(?P=result)\s*=\s*(?P=cursor)\s*,\s*\(\s*\(\s*'
        rf'{field("(?P=cursor)", "s32", "(?P<ymax>" + NUM + ")")}\s*<\s*(?P=y)\s*\)\s*!=\s*0\s*\)\s*\)\s*\)\s*{{\s*'
        rf'(?P=cursor)\s*=\s*{field("(?P=cursor)", "void\\s*\\*", "(?P<next>" + NUM + ")")}\s*;\s*'
        rf'(?P=result)\s*=\s*NULL\s*;\s*if\s*\(\s*\(\s*\(\s*s32\s*\)\s*(?P=cursor)\s*!=\s*'
        rf'\(\s*s32\s*\)\s*(?P=head)\s*\)\s*&\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*\)\s*{{\s*'
        rf'goto\s+(?P=label)\s*;\s*}}\s*}}\s*return\s+(?P=result)\s*;\s*'
    )
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    m = pattern.fullmatch(part.body)
    if not m or len({m[k] for k in ('x', 'y', 'cursor', 'result', 'head', 'point')}) != 6:
        return []
    if not re.search(rf'\b{re.escape(name)}\s*\(\s*void\s*\*\s*{m["head"]}\s*,\s*'
                     rf'void\s*\*\s*{m["point"]}\s*\)\s*$', part.clean[:part.opening]):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in ('x', 'y', 'cursor', 'result', 'head', 'point')):
        return []
    if re.search(r'\b__repair_y_min\b', part.clean + '\n' + header):
        return []
    offsets = [int(m[k], 0) for k in ('xmin', 'xmax', 'ymin', 'ymax', 'next')]
    for off in offsets:
        if not re.search(rf'\b(?:lw) \$\w+, (?:0x{off:x}|{off})\(\$a2\)', target):
            return []
    # The temporary enforces the target's lower-bound load before the point read.
    body = f'''
    s32 {m['x']}, {m['y']}, __repair_y_min;
    void *{m['cursor']};
    {m['cursor']} = {m['head']};
    {m['x']} = M2C_FIELD({m['point']}, s32 *, 0);
    do {{
        if ({m['x']} >= M2C_FIELD({m['cursor']}, s32 *, {m['xmin']}) &&
            M2C_FIELD({m['cursor']}, s32 *, {m['xmax']}) >= {m['x']}) {{
            __repair_y_min = M2C_FIELD({m['cursor']}, s32 *, {m['ymin']});
            {m['y']} = M2C_FIELD({m['point']}, s32 *, 8);
            if ({m['y']} >= __repair_y_min && M2C_FIELD({m['cursor']}, s32 *, {m['ymax']}) >= {m['y']})
                return {m['cursor']};
        }}
        {m['cursor']} = M2C_FIELD({m['cursor']}, void **, {m['next']});
    }} while ({m['cursor']} != {m['head']} && {m['cursor']} != NULL);
    return NULL;
'''
    return [('measured_region_search', edit(source, [(part.opening + 1, part.end - 1, body)]))]
