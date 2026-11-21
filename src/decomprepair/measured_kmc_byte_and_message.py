"""Propose two KMC byte and stack-pointer scheduling repairs from measured mismatches."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close


def variants(source, name, header, rows):
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changed = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    result = []
    # KMC loads char with lbu and sign-extends it separately. The target omits that extension.
    for load in re.finditer(rf'lbu (\$\w+), %lo\(({IDENT})\)\(\$\w+\)', target):
        reg, symbol = load.groups()
        if ((('', f'sll {reg}, {reg}, 24') not in changed)
                or (('', f'sra {reg}, {reg}, 24') not in changed)):
            continue
        declaration = re.search(rf'\bextern\s+char\s+{re.escape(symbol)}\s*\[\s*\]\s*;', part.clean[:part.opening])
        if (not declaration or re.search(rf'\b{re.escape(symbol)}\b', header or '')
                or not re.search(rf'\b{re.escape(symbol)}\b', part.body)):
            continue
        pos = declaration.start() + declaration.group().index('char')
        result.append(('measured_unsigned_byte_array', edit(source, [(pos, pos, 'unsigned ')])))

    # An output pointer returned through a stack slot is read before a flag is cleared.
    if len(rows) != 25 or len(changed) != 8:
        return result
    required = [('','andi $v0, $v0, 65534'), ('','sh $v0, 14($s0)'),
                ('lw $v1, 16($sp)','lw $v0, 16($sp)'),
                ('andi $v0, $v0, 65534',''), ('sh $v0, 14($s0)','nop')]
    if not all(pair in changed for pair in required):
        return result
    body = part.body
    pattern = re.compile(
        rf'(?P<call>{IDENT}\([^;]*&(?P<slot>{IDENT})\s*,\s*1\s*\);)\s*'
        rf'(?P<clear>M2C_FIELD\((?P<arg>{IDENT}), u16 \*, (?P<offset>{NUMBER})\) = '
        rf'\(u16\) \(M2C_FIELD\((?P=arg), u16 \*, (?P=offset)\) & 0xFFFE\);)\s*'
        rf'if \((?P=slot) == NULL\) \{{ goto (?P<label>{IDENT}); \}}\s*return \*(?P=slot);'
    )
    hit = pattern.search(body)
    if (not hit or int(hit['offset'], 0) != 14 or len(re.findall(rf'\b{hit["slot"]}\b', body)) != 4
            or not re.search(rf'\bs32\s*\*{hit["slot"]}\s*;', body)
            or re.search(r'\bvolatile\b|\b__repair_message\b', part.clean)):
        return result
    start = part.opening + 1
    fixed = edit(source, [(start, start, '\n    s32 *__repair_message;'),
                          (start + hit.start(), start + hit.end(),
                           hit.group().replace(hit['clear'], f'__repair_message = {hit["slot"]};\n    '+hit['clear'])
                           .replace(f'if ({hit["slot"]} == NULL)', 'if (__repair_message == NULL)')
                           .replace(f'return *{hit["slot"]};', 'return *__repair_message;'))])
    result.append(('measured_stack_message_schedule', fixed))
    return result
