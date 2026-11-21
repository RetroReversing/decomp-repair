"""MIPS branch repairs where the target shows a specific live scalar or store order."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for


def variants(part, name, header, rows, changed):
    if len(changed) == 5 and (candidate := _mask_divisor(part, name, header, rows, changed)):
        return [('measured_divisor_store_order', candidate)]
    if len(changed) == 6 and (candidate := _mode_branches(part, header, rows, changed)):
        return [('measured_mode_defaults', candidate)]
    return []


def _mask_divisor(part, name, header, rows, changed):
    first = changed[0]
    if first < 1 or changed != [first, first + 1, first + 3, first + 4, first + 8]:
        return None
    _, target, actual = rows[first]
    mask = re.fullmatch(rf'andi (\$a[0-3]), \1, ({NUMBER})', target)
    draft = re.fullmatch(rf'andi (\$\w+), (\$a[0-3]), ({NUMBER})', actual)
    before = re.fullmatch(rf'sw (\$\w+), ({NUMBER})\(\$\w+\)', rows[first - 1][1])
    if (not mask or not draft or not before or mask[1] == draft[1] or mask[1] != draft[2]
            or integer(mask[2]) != integer(draft[3]) or before[1] != draft[1]):
        return None
    for index, opcode in zip(changed[1:], ('beqz', 'div', 'bnez', 'bne')):
        marker, want, have = rows[index]
        if marker != 'r' or not want.startswith(opcode + ' ') or have != want.replace(mask[1], draft[1]):
            return None
    constant = re.fullmatch(rf'addiu (\$\w+), \$zero, ({NUMBER})', rows[first + 2][1])
    if not constant or rows[first + 3][1] != f'div $zero, {constant[1]}, {mask[1]}':
        return None
    signature = re.search(rf'\b{re.escape(name)}\(([^()]+)\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    params = signature[1].split(',')
    index = int(mask[1][-1])
    formal = re.fullmatch(rf'\s*s32\s+({IDENT})\s*', params[index]) if index < len(params) else None
    if not formal:
        return None
    parameter = formal[1]
    shape = re.compile(
        rf'(?m)^\s*M2C_FIELD\({IDENT},\s*(?P<type>s32)\s*\*,\s*(?P<offset>{NUMBER})\)\s*=\s*(?P<local>{IDENT});'
        rf'\s*(?P<mask>(?P=local)\s*=\s*{parameter}\s*&\s*(?P<bits>{NUMBER});)'
        rf'\s*if\s*\(\s*(?P<test>(?P=local))\s*!=\s*0\s*\)\s*{{'
        rf'\s*(?P<field>M2C_FIELD\([^;\n]+\))\s*=\s*\(s32\)\s*\(\s*(?P<numerator>{NUMBER})\s*/\s*'
        rf'(?P<divisor>(?P=local))\s*\);\s*}}\s*else\s*{{\s*(?P=field)\s*=\s*(?P<fallback>{NUMBER});\s*}}')
    locals_ = {decl['name'] for decl in locals_for(part)}
    found = list(shape.finditer(part.clean, part.opening + 1, part.end))
    if len(found) != 1:
        return None
    hit = found[0]
    if (hit['local'] not in locals_ or hit['local'] == parameter or integer(hit['offset']) != integer(before[2])
            or integer(hit['bits']) != integer(mask[2]) or integer(hit['numerator']) != integer(constant[2])
            or integer(hit['fallback']) != integer(constant[2])
            or re.search(rf'\b(?:{parameter}|{hit["local"]})\b', hit['field'])
            or re.search(rf'\b(?:{parameter}|{hit["local"]})\b', part.clean[hit.end():part.end])
            or re.search(rf'&\s*{parameter}\b|\b(?:goto|asm|setjmp|longjmp)\b', part.body)
            or re.search(rf'(?m)^\s*#\s*define\s+{parameter}\b', header + '\n' + part.clean)):
        return None
    return edit(part.source, [(*hit.span('type'), 'volatile s32'),
                              (*hit.span('mask'), f'{parameter} &= {hit["bits"]};'),
                              (*hit.span('test'), parameter), (*hit.span('divisor'), parameter)])


def _mode_branches(part, header, rows, changed):
    if len(rows) != 18 or changed != [1, 2, 4, 6, 7, 15]:
        return None
    load = re.fullmatch(rf'lbu \$a1, ({NUMBER})\(\$v1\)', rows[1][1])
    threshold = re.fullmatch(rf'sltiu \$v0, \$a1, ({NUMBER})', rows[2][1])
    low = re.fullmatch(rf'addiu \$v0, \$zero, ({NUMBER})', rows[4][1])
    special = re.fullmatch(rf'addiu \$v0, \$zero, ({NUMBER})', rows[5][1])
    high = re.fullmatch(rf'addiu \$v0, \$zero, ({NUMBER})', rows[7][1])
    output = re.fullmatch(rf'sw \$v0, ({NUMBER})\(\$v1\)', rows[15][1])
    if (not all((load, threshold, low, special, high, output))
            or rows[3][1] != 'bnez $v0, 0x3c' or rows[6][1] != 'bne $a1, $v0, 0x3c'
            or rows[16][1] != 'jr $ra'):
        return None
    for i in (1, 2, 6):
        if rows[i][0] != 'r' or rows[i][2] != rows[i][1].replace('$a1', '$a2'):
            return None
    for i in (4, 7, 15):
        if rows[i][0] != 'r' or rows[i][2] != rows[i][1].replace('$v0', '$a1'):
            return None

    source = re.compile(
        rf'(?m)^[ \t]*(?P<mode>{IDENT}) = M2C_FIELD\((?P<base>{IDENT}), u8 \*, (?P<offset>{NUMBER})\);\s*'
        rf'(?P<rewrite>(?P<result>{IDENT}) = (?P<low>{NUMBER});\s*'
        rf'if \((?P=mode) >= (?P<threshold>{NUMBER})\) {{\s*'
        rf'(?P=result) = (?P<high>{NUMBER});\s*if \((?P=mode) == (?P<special>{NUMBER})\) {{\s*'
        rf'(?P<body>[^{{}}]+?return\s*;)\s*}}\s*}})\s*'
        rf'M2C_FIELD\((?P=base), s32 \*, (?P<output>{NUMBER})\) = (?P=result);')
    hit = source.search(part.clean, part.opening + 1, part.end)
    if not hit:
        return None
    for key, value in zip(('offset', 'threshold', 'low', 'special', 'high', 'output'),
                          (load, threshold, low, special, high, output)):
        if integer(hit[key]) != integer(value[1]):
            return None
    locals_ = {decl['name']: decl['type'] for decl in locals_for(part)}
    result, mode = hit['result'], hit['mode']
    if (locals_.get(mode) != 'u8' or locals_.get(result) != 's32'
            or re.search(rf'\b(?:{result}|goto|asm|if|else|switch|for|while|do)\b', hit['body'])
            or re.search(rf'(?m)^\s*#\s*define\s+(?:{result}|{mode})\b', header + '\n' + part.clean)):
        return None
    original = part.source[slice(*hit.span('body'))]
    body = '\n        '.join(line.strip() for line in original.splitlines())
    replacement = (f'if ({mode} < {hit["threshold"]}) {{\n        {result} = {hit["low"]};\n'
                   f'    }} else if ({mode} == {hit["special"]}) {{\n        {body}\n'
                   f'    }} else {{\n        {result} = {hit["high"]};\n    }}')
    return edit(part.source, [(*hit.span('rewrite'), replacement)])
