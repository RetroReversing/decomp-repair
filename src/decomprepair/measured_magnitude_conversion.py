"""Initialize a measured magnitude and stage its floating conversion."""

import re

from .integer_repair_support import IDENT, edit, view

TARGET = re.compile(
    rf'c\.lt\.s \$f2, \$f0\nmov\.s \$f4, \$f2\nnop\nbc1f [^\n]+\n'
    rf'swc1 \$f2, (?P<phase>0x[0-9a-fA-F]+|[0-9]+)\(\$a0\)\nneg\.s \$f4, \$f2\n'
    rf'lui \$at, %hi\((?P<const>{IDENT})\)\nldc1 \$f0, %lo\((?P=const)\)\(\$at\)\n'
    rf'cvt\.d\.s \$f2, \$f4\nsub\.d \$f2, \$f2, \$f0\n'
    rf'lwc1 \$f0, (?P<depth>0x[0-9a-fA-F]+|[0-9]+)\(\$a0\)\ncvt\.s\.d \$f2, \$f2'
)
CANDIDATE = re.compile(
    r'c\.lt\.s \$f2, \$f0\nnop\nnop\nbc1f [^\n]+\n'
    r'swc1 \$f2, [^\n]+\nneg\.s \$f6, \$f2'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t = TARGET.search(target)
    if not t or not CANDIDATE.search(candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean):
        return []
    pattern = re.compile(
        rf'(?P<old>{IDENT})\s*=\s*(?P<phase>{IDENT})\s*;\s*'
        rf'\(\(\s*(?P<type>__repair_record_{IDENT})\s*\*\s*\)\s*(?P<obj>{IDENT})\s*\)\s*'
        rf'->\s*field_(?P<phaseoff>[0-9a-fA-F]+)\s*=\s*(?P=phase)\s*;\s*'
        rf'if\s*\(\s*(?P=phase)\s*<\s*0\.0[fF]\s*\)\s*{{\s*'
        rf'(?P<mag>{IDENT})\s*=\s*-\s*(?P=phase)\s*;\s*}}\s*'
        rf'return\s+(?P<depthexpr>\(\(\s*(?P=type)\s*\*\s*\)\s*(?P=obj)\s*\)\s*'
        rf'->\s*field_(?P<depthoff>[0-9a-fA-F]+))\s*\*\s*\(f32\)\s*\(\s*\(f64\)\s*'
        rf'(?P=mag)\s*-\s*(?P<const>{IDENT})\s*\)\s*;'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if (int(m['phaseoff'], 16) != int(t['phase'], 0) or int(m['depthoff'], 16) != int(t['depth'], 0)
            or m['const'] != t['const'] or len({m['old'], m['phase'], m['mag']}) != 3):
        return []
    for key in ('old', 'phase', 'mag'):
        if not re.search(rf'\bf32\s+{re.escape(m[key])}\s*;', part.body):
            return []
    if len(re.findall(rf'\b{re.escape(m["old"])}\b', part.body)) != 2:
        return []
    if len(re.findall(rf'\b{re.escape(m["mag"])}\b', part.body)) != 3:
        return []
    if not re.search(rf'\bextern\s+f64\s+{re.escape(m["const"])}\s*;', part.clean[:part.opening] + '\n' + header):
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(m[k])}\b', source + '\n' + header)
           for k in ('old', 'phase', 'mag', 'obj', 'const')):
        return []
    original = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    # The old local was assigned but never used, while the magnitude was only
    # written on the negative path. Initialize the latter on both paths.
    replacement = (f'{m["mag"]} = {m["phase"]};\n'
                   f'    (({m["type"]}*){m["obj"]})->field_{m["phaseoff"]} = {m["phase"]};\n'
                   f'    if ({m["phase"]} < 0.0f) {{\n        {m["mag"]} = -{m["phase"]};\n    }}\n'
                   f'    {m["phase"]} = (f32) ((f64) {m["mag"]} - {m["const"]});\n'
                   f'    return {m["depthexpr"]} * {m["phase"]};')
    return [('measured_magnitude_conversion', edit(source, [(part.opening + 1 + m.start(),
                                                               part.opening + 1 + m.end(), replacement)]))]
