"""MIPS branch repairs where the target shows a specific live scalar or store order."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for


def variants(part, name, header, rows, changed):
    if len(changed) == 1:
        return _lookup_loop_exit(part, header, rows, changed[0])
    if len(changed) == 5 and (candidate := _mask_divisor(part, name, header, rows, changed)):
        return [('measured_divisor_store_order', candidate)]
    if len(changed) == 6 and (candidate := _mode_branches(part, header, rows, changed)):
        return [('measured_mode_defaults', candidate)]
    if len(changed) == 3 and (candidate := _branch_constant_store(part, header, rows, changed)):
        return [('measured_branch_constant_store', candidate)]
    return []


def _lookup_loop_exit(part, header, rows, index):
    """Route the second zero-count check to the function's shared tail."""
    target, actual = rows[index][1:]
    branch = re.fullmatch(rf'beqz (\$\w+), ({NUMBER})', target)
    if not branch or not re.fullmatch(rf'beqz {re.escape(branch[1])}, {NUMBER}', actual):
        return []
    # The earlier zero check already exits, and only the generated loop check lands at the match.
    previous = next((i for i in range(index - 1, max(-1, index - 10), -1)
                     if rows[i][1] == rows[i][2] == target), None)
    if previous is None or not previous or not re.match(rf'lhu {re.escape(branch[1])}, ', rows[previous - 1][1]):
        return []
    if not any(row[1] == row[2] and re.fullmatch(r'beq \$\w+, \$\w+, ' + re.escape(actual.rsplit(' ', 1)[1]),
                                                 row[1]) for row in rows[index + 1:index + 14]):
        return []
    loop = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)for\s*\(\s*(?P<i>{IDENT})\s*=\s*0\s*;\s*(?P=i)\s*<\s*(?P<n>{IDENT})'
        rf'\s*;\s*(?P=i)\+\+\s*\)\s*{{\s*if\s*\(\s*'
        rf'(?P<test>{IDENT}\s*\[\s*{IDENT}\s*\+\s*(?P=i)\s*\]\s*\.\s*{IDENT}\s*==\s*{IDENT})'
        r'\s*\)\s*{\s*break\s*;\s*}\s*}'
    )
    hits = list(loop.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return []
    hit = hits[0]
    n, counter, indent = hit['n'], hit['i'], hit['indent']
    prefix = part.clean[part.opening + 1:hit.start()]
    if not re.search(rf'\b{n}\s*=\s*{IDENT}\s*\[\s*{IDENT}\s*\]\s*\.\s*{IDENT}\s*;\s*'
                     rf'if\s*\(\s*{n}\s*!=\s*0\s*\)\s*{{\s*'
                     rf'{IDENT}\s*=\s*{IDENT}\s*\[\s*{IDENT}\s*\]\s*\.\s*{IDENT}\s*;\s*$', prefix):
        return []
    if prefix.count('{') - prefix.count('}') != 1:
        return []
    suffix = part.clean[hit.end():part.end]
    tail = re.search(rf'(?m)^([ \t]*)({IDENT}\s*\(\s*\)\s*;\s*return\s+0\s*;\s*}})\s*$', suffix)
    if not tail or suffix[:tail.start()].count('}') - suffix[:tail.start()].count('{') != 1:
        return []
    if re.search(r'\b(?:repair_lookup_exit|repair_lookup_scan|repair_lookup_found)\b', part.clean + '\n' + header):
        return []
    if re.search(r'/[*/]', part.source[hit.start():hit.end()]):
        return []
    test = part.source[slice(*hit.span('test'))]
    replacement = (
        f'{indent}{counter} = 0;\n'
        f'{indent}if (!(unsigned short){n}) goto repair_lookup_exit;\n'
        f'{indent}repair_lookup_scan: if ({test}) goto repair_lookup_found;\n'
        f'{indent}if (++{counter} < {n}) goto repair_lookup_scan;\n'
        f'{indent}repair_lookup_found: ;'
    )
    tail_at = hit.end() + tail.start(2)
    edits = [(hit.start(), hit.end(), replacement), (tail_at, tail_at, 'repair_lookup_exit: ')]
    result = [('measured_lookup_loop_exit', edit(part.source, edits))]
    # Explicit loop entry can shrink the frame. Try a naturally aligned reservation
    # only when the source already has an unreferenced two-word pad at entry.
    pad = re.match(r'\s*(?P<decl>volatile\s+s32\s+(?P<name>pad\w*)\s*\[\s*2\s*\]\s*;)', prefix)
    if pad and len(re.findall(rf'(?<![\w.>]){pad["name"]}\b', part.body)) == 1:
        opening = part.opening + 1
        start, stop = pad.span('decl')
        result.append(('measured_lookup_loop_exit_aligned',
                       edit(part.source, [*edits, (opening + start, opening + stop, f'f64 {pad["name"]}[2];')])))
    return result


def _branch_constant_store(part, header, rows, changed):
    first, second, store = changed
    if first < 3 or second != first + 1 or store != first + 3:
        return None
    default = re.fullmatch(rf'addiu (\$v[01]), \$zero, ({NUMBER})', rows[first][1])
    if not default:
        return None
    register, value = default.groups()
    alternate = re.fullmatch(rf'addiu {re.escape(register)}, \$zero, ({NUMBER})', rows[second][1])
    output = re.fullmatch(rf'(sb|sh|sw) {re.escape(register)}, %lo\(({IDENT})\)\(\$at\)', rows[store][1])
    load = re.fullmatch(rf'(?:lb|lbu|lh|lhu|lw) {re.escape(register)}, %lo\(({IDENT})\)\({re.escape(register)}\)',
                        rows[first - 2][1])
    if not alternate or not output or not load:
        return None
    branch = re.fullmatch(rf'bnez {re.escape(register)}, ({NUMBER})', rows[first - 1][1])
    if (not branch or integer(branch[1]) != (store - 1) * 4
            or rows[first - 3][1] != f'lui {register}, %hi({load[1]})'
            or rows[store - 1][1] != f'lui $at, %hi({output[2]})'):
        return None
    other = '$v1' if register == '$v0' else '$v0'
    if any(rows[i][0] != 'r' or rows[i][2] != rows[i][1].replace(register, other) for i in changed):
        return None

    scalar, destination = load[1], output[2]
    shape = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<local>{IDENT})\s*=\s*(?P<default>{NUMBER});\s*'
        rf'if\s*\(\s*{scalar}\s*==\s*0\s*\)\s*{{\s*(?P=local)\s*=\s*(?P<alt>{NUMBER});'
        rf'\s*}}\s*{destination}\s*=\s*(?P=local);')
    hits = list(shape.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    temporary = hit['local']
    types = {decl['name']: decl['type'] for decl in locals_for(part)}
    width = {'s8': 8, 'u8': 8, 's16': 16, 'u16': 16, 's32': 32, 'u32': 32}.get(types.get(temporary))
    if width is None or re.search(rf'(?m)^\s*#\s*define\s+(?:{temporary}|{scalar}|{destination})\b',
                                  header + '\n' + part.clean):
        return None
    values = integer(hit['default']), integer(hit['alt'])
    signed = types[temporary].startswith('s')
    bound = 1 << (width - signed)
    lower = -bound if signed else 0
    if values != (integer(value), integer(alternate[1])) or not all(lower <= n < bound for n in values):
        return None
    if len(re.findall(rf'\b{temporary}\b', part.clean[part.opening + 1:part.end])) != 4:
        return None
    indent = hit['indent']
    return edit(part.source, [(*hit.span(), (
        f'{indent}if ({scalar}) {{\n{indent}    {destination} = {hit["default"]};\n'
        f'{indent}}} else {{\n{indent}    {destination} = {hit["alt"]};\n{indent}}}'))])


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
