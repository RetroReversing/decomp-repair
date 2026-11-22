"""Stage an accumulator multiply around an independent packing-loop counter."""

import re

from .integer_repair_support import IDENT, edit, locals_for, view

REG = r'\$[a-z0-9]+'
TARGET = re.compile(
    rf'lbu (?P<byte>{REG}), [^\n]+\n'
    rf'sll (?P<acc>{REG}), (?P=acc), (?P<shift>[1-9][0-9]*)\n'
    rf'addiu (?P<counter>{REG}), (?P=counter), 1\n'
    rf'or (?P=acc), (?P=acc), (?P=byte)'
)
CANDIDATE = re.compile(
    rf'lbu (?P<byte>{REG}), [^\n]+\n'
    rf'addiu (?P<counter>{REG}), (?P=counter), 1\n'
    rf'sll (?P<tmp>{REG}), (?P<acc>{REG}), (?P<shift>[1-9][0-9]*)\n'
    rf'or (?P=acc), (?P=tmp), (?P=byte)'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or t['shift'] != c['shift'] or t['acc'] != c['acc']:
        return []
    shift = int(t['shift'])
    if not 1 <= shift <= 30:
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    locals_ = {decl['name']: decl['type'] for decl in locals_for(part)}
    pattern = re.compile(
        rf'(?P<counter>{IDENT})\s*\+=\s*1\s*;\s*'
        rf'(?P<acc>{IDENT})\s*=\s*\(\s*(?P=acc)\s*\*\s*'
        rf'(?P<factor>0[xX][0-9a-fA-F]+|[0-9]+)\s*\)\s*\|\s*(?P<byte>{IDENT})\s*;'
    )
    result = []
    for m in pattern.finditer(part.body):
        if (len({m['counter'], m['acc'], m['byte']}) != 3 or locals_.get(m['counter']) != 's32'
                or locals_.get(m['acc']) != 's32' or locals_.get(m['byte']) != 'u8'
                or int(m['factor'], 0) != 1 << shift):
            continue
        if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(m[x])}\b', source + '\n' + header)
               for x in ('counter', 'acc', 'byte')):
            continue
        original = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
        if '/*' in original or '//' in original:
            continue
        replacement = (f'{m["acc"]} = {m["acc"]} * {m["factor"]};\n'
                       f'        {m["counter"]} += 1;\n        {m["acc"]} |= {m["byte"]};')
        result.append(('measured_packing_stage', edit(source, [(part.opening + 1 + m.start(),
                                                                part.opening + 1 + m.end(), replacement)])))
    return result[:1]
