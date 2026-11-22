"""Recover a measured command-word packing and end-pointer schedule."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
PACK_T = re.compile(r'sll \$a1, \$a1, 0x10\nsll \$a2, \$a2, 1\nandi \$a2, \$a2, 0xffff\n'
                    r'or \$a1, \$a1, \$a2')
PACK_C = re.compile(r'sll \$a2, \$a2, 1\nandi \$a2, \$a2, 0xffff\nsll \$a1, \$a1, 0x10\n'
                    r'or \$a1, \$a1, \$a2')
OR_T = re.compile(rf'lbu \$v0, (?P<byte>{NUM})\(\$s1\)\nlhu \$v1, (?P<half>{NUM})\(\$s1\)\n'
                  rf'lui \$a0, (?P<const>{NUM})\nsll \$v0, \$v0, 0x10\n'
                  r'or \$v1, \$v1, \$a0\nor \$v0, \$v0, \$v1')
OR_C = re.compile(rf'lbu \$v0, (?P<byte>{NUM})\(\$s1\)\nlhu \$a0, (?P<half>{NUM})\(\$s1\)\n'
                  rf'lui \$v1, (?P<const>{NUM})\nsll \$v0, \$v0, 0x10\n'
                  r'or \$v0, \$v0, \$v1\nor \$v0, \$v0, \$a0')
END_T = re.compile(rf'addiu \$s0, \$s0, (?P<end>{NUM})\nmove \$v0, \$s0')
END_C = re.compile(rf'addiu \$v0, \$s0, (?P<end>{NUM})')


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c, et, ec = OR_T.search(target), OR_C.search(candidate), END_T.search(target), END_C.search(candidate)
    if not all((PACK_T.search(target), PACK_C.search(candidate), t, c, et, ec)):
        return []
    if any(int(t[k], 0) != int(c[k], 0) for k in ('byte', 'half', 'const')) or et['end'] != ec['end']:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    init = re.compile(rf'(?P<temp>{IDENT})\s*=\s*\(\s*(?P<arg>{IDENT})\s*\*\s*2\s*\)\s*&\s*0[xX][fF]{{4}}\s*;')
    inits = list(init.finditer(part.body))
    if len(inits) != 1:
        return []
    m = inits[0]
    temp, arg = m['temp'], m['arg']
    if not re.search(rf'\bs32\s+{re.escape(temp)}\s*;', part.body):
        return []
    if not re.search(rf'\bs32\s+{re.escape(arg)}\b', part.clean[:part.opening]):
        return []
    refs = list(re.finditer(rf'\b{re.escape(temp)}\b', part.body))
    if len(refs) != 4 or sum(r.start() > m.end() for r in refs) != 2:
        return []
    if re.search(rf'&\s*{re.escape(arg)}\b|\b{re.escape(arg)}\s*(?:[+*/%&|^\-]?=(?!=)|\+\+|--)', part.body):
        return []
    packed = re.search(rf'\(\s*{IDENT}\s*<<\s*0[xX]10\s*\)\s*\|\s*{re.escape(temp)}\b', part.body[m.end():])
    call = re.search(rf'\b{IDENT}\s*\([^;{{}}]*,\s*{IDENT}\s*,\s*{re.escape(temp)}\s*\)', part.body[m.end():])
    if not packed or not call:
        return []
    expr = re.compile(
        rf'M2C_FIELD\(\s*(?P<out>{IDENT})\s*,\s*s32\s*\*\s*,\s*{NUM}\s*\)\s*=\s*\(s32\)\s*\(\s*'
        rf'\(\s*(?P<byte>M2C_FIELD\(\s*(?P<owner>{IDENT})\s*,\s*u8\s*\*\s*,\s*(?P<byteoff>{NUM})\s*\))\s*'
        rf'<<\s*0[xX]10\s*\)\s*\|\s*\(\s*(?P<half>M2C_FIELD\(\s*(?P=owner)\s*,\s*u16\s*\*\s*,\s*'
        rf'(?P<halfoff>{NUM})\s*\))\s*\|\s*(?P<const>{NUM})\s*\)\s*\)\s*;'
    )
    expressions = list(expr.finditer(part.body))
    if len(expressions) != 1:
        return []
    e = expressions[0]
    if (int(e['byteoff'], 0) != int(t['byte'], 0) or int(e['halfoff'], 0) != int(t['half'], 0)
            or int(e['const'], 0) != int(t['const'], 0) << 16):
        return []
    returns = list(re.finditer(rf'\breturn\s+{re.escape(e["out"])}\s*\+\s*(?P<offset>{NUM})\s*;', part.body))
    if len(returns) != 1 or int(returns[0]['offset'], 0) != int(et['end'], 0):
        return []
    if e.start() <= m.end() or returns[0].start() <= e.end():
        return []
    if not re.search(rf'\bvoid\s*\*\s*{re.escape(e["out"])}\b', part.clean[:part.opening]):
        return []
    if re.search(rf'&\s*{re.escape(e["out"])}\b|\b{re.escape(e["out"])}\s*(?:[+*/%&|^\-]?=(?!=)|\+\+|--)',
                 part.body):
        return []
    temp_name = '__repair_command_end'
    if re.search(rf'\b{temp_name}\b', source + '\n' + header):
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(x)}\b', source + '\n' + header)
           for x in (temp, arg, e['out'], e['owner'])):
        return []
    original = source[part.opening + 1 + m.start():part.opening + 1 + returns[0].end()]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    replacement = f'((({e["byte"]} << 0x10) | {e["const"]}) | {e["half"]})'
    edits = [(start, start, f'\n    void *{temp_name};'),
             (start + m.start(), start + m.end(), ''),
             (start + e.start(), start + e.start(), f'{temp_name} = (char *){e["out"]} + {returns[0]["offset"]};\n    '),
             (start + e.start('byte') - 1, start + e.end('const') + 1, replacement),
             (start + returns[0].start(), start + returns[0].end(), f'return {temp_name};')]
    edits += [(start + r.start(), start + r.end(), f'(({arg} * 2) & 0xFFFF)')
              for r in refs if r.start() > m.end()]
    return [('measured_command_word_schedule', edit(source, edits))]
