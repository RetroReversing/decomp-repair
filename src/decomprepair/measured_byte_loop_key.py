"""Stage a measured comparison address and recover a byte-sized loop read."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines

TARGET = re.compile(
    rf'lui \$s4, %hi\((?P<key>{IDENT})\)\naddiu \$s4, \$s4, %lo\((?P=key)\)\n'
    rf'move \$s1, \$zero\nlui \$v0, %hi\((?P<base>{IDENT})\)\n'
    rf'lw \$v0, %lo\((?P=base)\)\(\$v0\)\naddu \$v0, \$s1, \$v0\n'
    rf'lbu \$v0, \(\$v0\)\nbnel \$v0, \$s4, \d+'
)
LOAD = re.compile(
    rf'\*\(\s*(?P<kind>s32)\s*\*\s*\)\s*\(\s*(?P<index>{IDENT})\s*\+\s*'
    rf'M2C_FIELD\s*\(\s*&\s*(?P<base>{IDENT})\s*,\s*s32\s*\*\s*,\s*(?P<off>{NUMBER})\s*\)\s*\)'
    rf'\s*==\s*(?P<key>{IDENT})\b'
)


def variants(source, name, header, rows, flags, resolve):
    flags = set(flags or ())
    if not resolve or not flags.intersection({'-mgp32', '-mabi=32'}) or flags.intersection({'-m64', '-mgp64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}):
        return []
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    measured = TARGET.search(target)
    if not measured or 'lw $v0, ($v0)' not in candidate:
        return []
    if not re.search(rf'move \$s1, \$zero\nlui \$s4, %hi\({re.escape(measured["key"])}\)', candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    matches = list(LOAD.finditer(part.body))
    if len(matches) != 1:
        return []
    m = matches[0]
    if m['key'] != measured['key'] or len({m['index'], m['base'], m['key']}) != 3:
        return []
    base = resolve(m['base'])
    if base is None or resolve(measured['base']) != base + integer(m['off']):
        return []
    if not re.search(rf'\bextern\s+char\s+{re.escape(m["key"])}\s*\[\s*\]\s*;', part.clean[:part.opening]):
        return []
    if not re.search(rf'\bs32\s+{re.escape(m["index"])}\s*;', part.body[:m.start()]):
        return []
    initializations = list(re.finditer(rf'\b{re.escape(m["index"])}\s*=\s*0\s*;', part.body[:m.start()]))
    if len(initializations) != 1 or not re.search(r'\bdo\s*\{', part.body[initializations[0].end():m.start()]):
        return []
    if re.search(r'\b__repair_loop_key\b', part.clean + '\n' + header):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection((m['index'], m['base'], m['key'])):
        return []
    start = part.opening + 1
    init = initializations[0]
    return [('measured_byte_loop_key', edit(source, [
        (start, start, '\n    s32 __repair_loop_key;'),
        (start + init.start(), start + init.start(), f'__repair_loop_key = (s32) {m["key"]};\n        '),
        (start + m.start('kind'), start + m.end('kind'), 'u8'),
        (start + m.start('key'), start + m.end('key'), '__repair_loop_key'),
    ]))]
