"""Expression candidates tied to an observed MIPS instruction difference."""

import re

from . import local_flow, measured_branch_shapes
from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, locals_for, view

REG = r'\$\w+'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
MEMORY = re.compile(rf'(lhu|lw)\s+({REG}),\s*({NUM})?\(({REG})\)')
ADDIU = re.compile(rf'addiu\s+({REG}),\s*({REG}),\s*(-?{NUM})')
SHIFT2 = re.compile(rf'sll\s+({REG}),\s*({REG}),\s*(?:2|0x2)')
ADD = re.compile(rf'addu\s+({REG}),\s*({REG}),\s*({REG})')


def sign_test(source, part, rows, changed):
    if (changed != [len(rows)-1] or len(rows) < 2 or rows[-2][1] != 'jr $ra'
            or rows[-2][2] != 'jr $ra' or rows[-1][1] != 'slti $v0, $v0, 0'
            or not re.fullmatch(r'srl \$v0, \$v0, (?:31|0x1f)',rows[-1][2])):
        return None
    pattern = re.compile(rf'\breturn\s*\(\s*(?P<bit>(?P<value>{IDENT})'
                         r'\s*&\s*0[xX]80000000[uU])\s*\)\s*!=\s*0\s*;')
    sites = list(pattern.finditer(part.clean,part.opening+1,part.end))
    if len(sites) != 1:
        return None
    hit = sites[0]
    if not re.search(rf'\bs32\s+{hit["value"]}\s*(?=[;=])',part.body):
        return None
    return edit(source,[(*hit.span('bit'),f'{hit["value"]} >> 31')])


def field_after_advance(source, header, part, rows, changed):
    if len(changed) != 1 or changed[0]+1 >= len(rows):
        return None
    index = changed[0]
    want,have = (MEMORY.fullmatch(text) for text in rows[index][1:])
    step = ADDIU.fullmatch(rows[index+1][1])
    if (not want or not have or not step or rows[index+1][0] != ' '
            or want[1] != 'lhu' or (want[1],want[2],want[4]) != (have[1],have[2],have[4])
            or step[2] != want[4]):
        return None
    advance = int(step[3],0)
    old = integer(have[3] or '0')-advance
    new = integer(want[3] or '0')-advance
    if advance <= 0 or min(old,new) < 0 or old == new:
        return None
    pattern = re.compile(rf'\b(?P<base>{IDENT})\s*\+=\s*(?P<count>{NUM})\s*;\s*'
                         rf'if\s*\(\s*\(\s*\(\s*(?P<record>{IDENT})\s*\*\s*\)\s*(?P=base)\s*\)'
                         rf'\s*->\s*(?P<member>field_(?P<offset>[0-9a-fA-F]+))\s*!=\s*0\s*\)\s*goto\s+{IDENT}\s*;')
    context = _blank(header)+'\n'+part.clean[:part.opening]
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        if integer(hit['count'])*2 != advance or int(hit['offset'],16) != old:
            continue
        if not re.search(rf'\bextern\s+u16\s*\*\s*{hit["base"]}\s*;',context):
            continue
        records = re.findall(rf'\btypedef\s+struct\s*{{([^{{}}]*)}}\s*{hit["record"]}\s*;',context)
        if len(records) != 1:
            continue
        words = {int(offset,16):f'field_{offset}' for offset in
                 re.findall(r'\bu16\s+field_([0-9a-fA-F]+)\s*;',records[0])}
        if old in words and new in words:
            return edit(source,[(*hit.span('member'),words[new])])
    return None


def multiply_window(rows):
    for i in range(len(rows)-5):
        window = rows[i:i+6]
        target = [match.fullmatch(row[1]) for match,row in zip((SHIFT2,ADD,MEMORY,SHIFT2,ADDIU,ADD),window)]
        prior = [match.fullmatch(row[2]) for match,row in zip((SHIFT2,ADD,MEMORY,SHIFT2,ADDIU,ADD),window)]
        if not all(target+prior) or window[0][0] != ' ' or any(row[0] != 'r' for row in window[1:]):
            continue
        shift,add,load,scale,bias,final = target
        if (load[1]!='lw' or (load[1],load[3],load[4]) != (prior[2][1],prior[2][3],prior[2][4])
                or shift.groups() != prior[0].groups() or add.groups() != (shift[1],shift[1],shift[2])
                or prior[1].groups() != (shift[2],shift[1],shift[2])
                or scale.groups() != (shift[1],shift[1]) or prior[3].groups() != (shift[2],shift[2])
                or bias.groups() != (shift[1],shift[1],prior[4][3])
                or final.groups() != (load[2],load[2],shift[1])):
            continue
        literal = int(bias[3],0)
        if -32768 <= literal < 0:
            yield -literal


def bounded_scale(source, part, rows):
    biases = set(multiply_window(rows))
    if not biases:
        return None
    pattern = re.compile(rf'\bs32\s+(?P<acc>{IDENT})\s*=\s*(?P<expr>(?P<value>{IDENT})\s*\*\s*5)\s*;'
                         rf'\s*s32\s+{IDENT}\s*=\s*M2C_FIELD\([^;]+\)\s*;\s*'
                         rf'(?P=acc)\s*=\s*(?P<scale>\(\s*(?P=acc)\s*<<\s*2\s*\))\s*-\s*(?P<bias>{NUM})\s*;')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        value = hit['value']
        writes = re.findall(rf'\b{value}\s*(?:=(?!=)\s*([^;]+)|[+\-*/%&|^]=|\+\+|--)',part.body)
        if (integer(hit['bias']) in biases and len(writes)==1
                and len(re.findall(rf'\bs32\s+{value}\s*;',part.body)) == 1
                and re.fullmatch(rf'{IDENT}\s*&\s*(?:0[xX][fF]{{4}}|65535)',writes[0].strip())
                and not re.search(rf'&\s*{value}\b',part.body)):
            return edit(source,[(*hit.span('expr'),f'(({value} << 2) + {value}) << 2'),
                                (*hit.span('scale'),hit['acc'])])
    return None


def staged_negation(source, part, rows, changed):
    if len(changed) != 2:
        return None
    i,j = changed
    old,new = rows[i],rows[j]
    neg = re.fullmatch(rf'neg\.s\s+({REG}),\s*{REG}',new[1])
    if j-i != 4 or j+1 >= len(rows) or not neg or old[1] or old[2] != new[1] or new[2]:
        return None
    cvt = re.fullmatch(rf'cvt\.s\.w\s+({REG}),\s*\1',rows[j-1][1])
    if (not cvt or rows[j-1][0] != ' ' or rows[j+1][0] != ' '
            or rows[j+1][1] != f'c.lt.s {cvt[1]}, {neg[1]}'):
        return None
    pattern = re.compile(rf'\b(?P<negative>{IDENT})\s*=\s*-\s*(?P<arg>{IDENT})\s*;\s*'
                         rf'if\s*\(\s*\(\s*(?P<value>{IDENT})\s*=\s*(?P<convert>\(\s*f32\s*\)\s*'
                         rf'\(\s*(?P<input>{IDENT})\s*>>\s*1\s*\))\s*\)\s*<\s*(?P=negative)\s*\)')
    for hit in pattern.finditer(part.clean,part.opening+1,part.end):
        names = [hit[key] for key in ('negative','arg','value','input')]
        if (len(set(names)) != 4
                or re.search(r'\bvolatile\s+(?:f32|s32)\s+(?:'+'|'.join(names)+r')\b',part.clean)
                or not re.search(rf'\bs32\s+{hit["input"]}\s*;',part.body)
                or not all(re.search(rf'\bf32\s+{name}\s*(?=[,);])',part.clean[:hit.start()])
                           for name in names[:3])):
            continue
        return edit(source,[(*hit.span(),f'do {{ {hit["value"]} = {hit["convert"]}; }} while (0);\n'
                                         f'{hit["negative"]} = -{hit["arg"]};\n'
                                         f'if ({hit["value"]} < {hit["negative"]})')])
    return None


def _byte_lane_merge(part, header, rows, changed):
    """Keep the loaded byte live through the high-lane OR measured before a packed store."""
    if len(changed) != 1:
        return None
    row = changed[0]
    if rows[row][0] != 'r' or row < 5 or row + 2 >= len(rows):
        return None
    op = re.fullmatch(rf'or ({REG}), \1, ({REG})', rows[row][1])
    if not op:
        return None
    byte, flag = (re.escape(value) for value in op.groups())
    have = re.fullmatch(rf'or ({REG}), \1, {flag}', rows[row][2])
    if not have or have[1] == op[1]:
        return None
    result = re.escape(have[1])
    window = [target for _, target, _ in rows[row-5:row+3]]
    if not (re.match(rf'lbu {byte}, ', window[0])
            and window[1] == f'nor {have[1]}, $zero, {op[1]}'
            and re.fullmatch(rf'andi {result}, {result}, (?:255|0xff)', window[2])
            and re.fullmatch(rf'sll {result}, {result}, (?:16|0x10)', window[3])
            and re.fullmatch(rf'lui {flag}, (?:65280|0xff00)', window[4])
            and window[6] == f'or {have[1]}, {have[1]}, {op[1]}'
            and (store := re.fullmatch(rf'sw {result}, ({NUM})\({REG}\)', window[7]))):
        return None

    fresh = '__repair_inverted_byte'
    if fresh in part.source + header or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<dst>M2C_FIELD\({IDENT}, s32 \*, (?P<offset>{NUM})\))'
        rf' = \(s32\) \(\(\(~(?P<byte>{IDENT}) & (?:0x[fF]{{2}}|255)\) << (?:0x10|16)\)'
        r' \| \((?P=byte) \| 0[xX][fF]{2}000000\)\);'
    )
    sites = list(pattern.finditer(part.clean, part.opening+1, part.end))
    if len(sites) != 1 or integer(sites[0]['offset']) != integer(store[1]):
        return None
    hit = sites[0]
    name, indent = hit['byte'], hit['indent']
    start = part.opening + 1
    before = part.clean[start:hit.start()]
    declaration = re.search(rf'(?m)^[ \t]*(?P<type>u8)\s+{name};', before)
    initial = re.search(rf'(?m)^[ \t]*{name}\s*=\s*(?P<expr>\*\([^;\n]+\));', before)
    if (not declaration or not initial or declaration.start() >= initial.start()
            or len(re.findall(rf'\b{name}\b', part.body)) != 4):
        return None
    a, b = initial.span('expr')
    da, db = declaration.span('type')
    local_end = start + declaration.end()
    original = part.source[start+a:start+b]
    replacement = (f'{indent}{fresh} = (~{name} & 0xFF) << 16;\n'
                   f'{indent}{name} |= 0xFF000000;\n'
                   f'{indent}{hit["dst"]} = {fresh} | {name};')
    return edit(part.source, [(start+da, start+db, 'u32'),
                              (local_end, local_end, f'\n{indent}u32 {fresh};'),
                              (start+a, start+b, f'(u8) {original}'),
                              (*hit.span(), replacement)])


def _branch_field_evidence(rows, changed):
    if len(changed) == 5:
        return _branch_field_common_store(rows, changed)
    if len(changed) != 3:
        return None
    first, second, merge = changed
    if second != first + 1 or merge != first + 3 or merge + 3 >= len(rows):
        return None
    if any(rows[i][0] != 'r' for i in changed) or not rows[merge-1][1].startswith('j '):
        return None
    offset, mask = None, None
    for side in (1, 2):
        mask_op, load_op = sorted((rows[first][side], rows[second][side]))
        bits = re.fullmatch(rf'addiu ({REG}), \$zero, -({NUM})', mask_op)
        field = re.fullmatch(rf'lw ({REG}), ({NUM})?\(({REG})\)', load_op)
        mix = re.fullmatch(rf'and ({REG}), ({REG}), ({REG})', rows[merge][side])
        if not bits or not field or not mix or {mix[2], mix[3]} != {bits[1], field[1]} or bits[1] == field[1]:
            return None
        result, base = mix[1], field[3]
        observed_offset, observed_mask = integer(field[2] or '0'), integer(bits[2]) - 1
        if side == 1:
            offset, mask = observed_offset, observed_mask
        elif (offset, mask) != (observed_offset, observed_mask):
            return None
        if base in {'$sp', '$fp', '$s8'} or not 0 < mask <= 0xffff:
            return None
        again = re.fullmatch(rf'lw {re.escape(result)}, ({NUM})?\({re.escape(base)}\)', rows[merge+1][side])
        set_bit = re.fullmatch(rf'ori {re.escape(result)}, {re.escape(result)}, ({NUM})', rows[merge+2][side])
        store_row = merge + 3
        if rows[store_row][side] == 'jr $ra':
            store_row += 1
        if store_row >= len(rows):
            return None
        store = re.fullmatch(rf'sw {re.escape(result)}, ({NUM})?\({re.escape(base)}\)', rows[store_row][side])
        if (not again or not set_bit or not store or integer(again[1] or '0') != offset
                or integer(store[1] or '0') != offset or integer(set_bit[1]) != mask):
            return None
    return offset, mask


def _branch_field_common_store(rows, changed):
    first = changed[0]
    if changed != [first, *range(first + 3, first + 7)] or any(rows[i][0] != 'r' for i in changed):
        return None
    target = []
    for side in (1, 2):
        block = [rows[at][side] for at in range(first, first + 7)]
        bits = re.fullmatch(rf'addiu ({REG}), \$zero, -({NUM})', block[0])
        read = re.fullmatch(rf'lw ({REG}), ({NUM})?\(({REG})\)', block[1])
        if not bits or not read or not block[2].startswith('j '):
            return None
        set_, clear, merge, store = block[3:]
        update = re.fullmatch(rf'ori ({REG}), {re.escape(read[1])}, ({NUM})', set_)
        if not update or update[1] == bits[1] or read[3] in {'$sp', '$fp', '$s8'}:
            return None
        result, offset, base = map(re.escape, (update[1], read[2] or '', read[3]))
        if (clear != f'lw {update[1]}, {read[2] or ""}({read[3]})'
                or merge != f'and {update[1]}, {update[1]}, {bits[1]}'
                or not re.fullmatch(rf'sw {result}, {offset}\({base}\)', store)):
            return None
        mask = integer(update[2])
        if not 0 < mask <= 0xffff or integer(bits[2]) != mask + 1:
            return None
        target.append((integer(read[2] or '0'), mask, read[3]))
    return target[0][:2] if target[0] == target[1] else None


def _branch_field_update(part, name, header, rows, changed):
    """Keep a branch's flag update on its field instead of carrying a temporary to the join."""
    if not (target := _branch_field_evidence(rows, changed)) or 'M2C_FIELD' not in part.body:
        return None
    if re.search(r'\b(?:volatile|goto|asm|__asm__|setjmp|longjmp)\b|\b'+IDENT+r'\s*:(?!:)', part.body):
        return None
    pattern = re.compile(
        rf'(?m)^[ \t]*(?P<first>(?P<temp>{IDENT}) = (?P<field>M2C_FIELD\((?P<base>{IDENT}), '
        rf'(?:s32|u32) \*, (?P<offset>{NUM})\)) (?P<op>& ~|\| )(?P<mask>{NUM});)\s*}}\s*else\s*{{\s*'
        rf'(?P<second>(?P=temp) = (?P=field) (?P<other_op>& ~|\| )(?P<other>{NUM});)\s*}}'
        rf'(?P<tail>\n[ \t]*(?P=field) = (?P=temp);)'
    )
    matches = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(matches) != 1:
        return None
    hit = matches[0]
    offset, mask = target
    if (integer(hit['offset']) != offset or integer(hit['mask']) != mask
            or integer(hit['other']) != mask or hit['op'] == hit['other_op']):
        return None
    temp, base = hit['temp'], hit['base']
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{temp}|{base})\b', header + '\n' + part.clean):
        return None
    uses = list(re.finditer(rf'\b{temp}\b', part.body))
    decls = list(re.finditer(rf'(?m)^[ \t]*(?:s32|u32)\s+{temp}\s*;[ \t]*\n',
                            part.clean[:hit.start()]))
    if len(decls) != 1 or decls[0].start() < part.opening:
        return None
    changes = [(*hit.span('tail'), '')]
    if len(uses) == 4:
        changes.append((*decls[0].span(), ''))
    else:
        declaration = next((d for d in locals_for(part) if d['name'] == temp), None)
        flow = local_flow.analyze(part.source, name, declarations=[declaration]) if declaration else None
        at = hit.end('tail') - len(f'{hit["field"]} = {temp};')
        join = flow.at(at) if flow else None
        if not join or any(temp in flow.nodes[i].live for i in join.successors):
            return None
    for group, op, number in (('first', 'op', 'mask'), ('second', 'other_op', 'other')):
        operator = '&= ~' if hit[op] == '& ~' else '|= '
        changes.append((*hit.span(group), f'{hit["field"]} {operator}{hit[number]};'))
    return edit(part.source, changes)


def _inline_rounded_shift(part, header, rows, changed):
    """Keep the signed choice, shift and conversion in one expression for scheduling."""
    if len(changed) != 2:
        return None
    first, second = changed
    if first < 4 or second != first + 4:
        return None
    early, late = rows[first], rows[second]
    if early != ('o', '', late[1]) or late[0] != 'o' or late[2] or not late[1].startswith('neg.s '):
        return None
    branch, negative, positive, shift = (row[1] for row in rows[first - 4:first])
    integer_reg = re.fullmatch(rf'bltzl ({REG}), {NUM}', branch)
    if not integer_reg:
        return None
    reg = integer_reg[1]
    if (negative, positive, shift) != (f'addiu {reg}, {reg}, -1', f'addiu {reg}, {reg}, 1', f'sra {reg}, {reg}, 1'):
        return None
    transfer = re.fullmatch(rf'mtc1 {re.escape(reg)}, (\$f\d+)', rows[first + 1][1])
    if not transfer or rows[first + 2][1] != 'nop' or rows[first + 3][1] != f'cvt.s.w {transfer[1]}, {transfer[1]}':
        return None

    shape = re.compile(
        rf'\bif\s*\(\s*(?P<input>{IDENT})\s*>=\s*0\s*\)\s*{{\s*'
        rf'(?P<temp>{IDENT})\s*=\s*(?P=input)\s*\+\s*1\s*;\s*}}\s*else\s*{{\s*'
        rf'(?P=temp)\s*=\s*(?P=input)\s*-\s*1\s*;\s*}}\s*'
        rf'(?P<result>{IDENT})\s*=\s*\(\s*(?P<cast>f32|float)\s*\)\s*\(\s*(?P=temp)\s*>>\s*1\s*\)\s*;')
    hits = list(shape.finditer(part.clean, part.opening + 1, part.end))
    if len(hits) != 1:
        return None
    hit = hits[0]
    value, temp, result = hit['input'], hit['temp'], hit['result']
    locals_ = {decl['name']: decl['type'] for decl in locals_for(part)}
    if (len({value, temp, result}) != 3 or locals_.get(value) != 's32' or locals_.get(temp) != 's32'
            or len(re.findall(rf'\b{temp}\b', part.body)) != 4
            or re.search(rf'(?m)^\s*#\s*define\s+(?:{value}|{temp}|{result})\b', header + '\n' + part.clean)
            or re.search(r'\b(?:goto|asm|__asm__|volatile)\b', part.body)):
        return None
    return edit(part.source, [(*hit.span(), f'{result} = ({hit["cast"]})(({value} >= 0 ? {value} + 1 : {value} - 1) >> 1);')])


def _square_vector_locals(part, header, rows, changed):
    """Reuse each difference for its square when the float dataflow is register-only."""
    if not 2 <= len(changed) <= 9:
        return None
    operations = {'lwc1', 'sub.s', 'mul.s', 'add.s'}
    if any(mark != 'r' or target.split(' ', 1)[0] not in operations
           or target.split(' ', 1)[0] != actual.split(' ', 1)[0]
           for mark, target, actual in (rows[i] for i in changed)):
        return None
    if not any(rows[i][1].startswith('sub.s ') for i in changed):
        return None
    pattern = re.compile(
        rf'(?m)^(?P<indent>[ \t]*)(?P<call>{IDENT})\s*\(\s*'
        rf'\(\s*(?P<x>{IDENT})\s*\*\s*(?P=x)\s*\)\s*\+\s*'
        rf'\(\s*(?P<y>{IDENT})\s*\*\s*(?P=y)\s*\)\s*\+\s*'
        rf'\(\s*(?P<z>{IDENT})\s*\*\s*(?P=z)\s*\)\s*\)\s*;\s*$')
    hit = pattern.search(part.clean, part.opening + 1, part.end)
    if not hit or not re.fullmatch(r'\s*}\s*', part.clean[hit.end():part.end]):
        return None
    names = [hit[key] for key in ('x', 'y', 'z')]
    if len(set(names)) != 3:
        return None
    prefix = part.clean[part.opening + 1:hit.start()]
    field = rf'M2C_FIELD\(\s*({IDENT})\s*,\s*const\s+f32\s*\*\s*,\s*({NUM})\s*\)'
    assignments = list(re.finditer(rf'\b({IDENT})\s*=\s*{field}\s*-\s*{field}\s*;', prefix))
    if [assignment[1] for assignment in assignments] != names:
        return None
    bases = {(assignment[2], assignment[4]) for assignment in assignments}
    offsets = [(integer(assignment[3]), integer(assignment[5])) for assignment in assignments]
    if len(bases) != 1 or offsets != [(0, 0), (4, 4), (8, 8)]:
        return None
    for local in names:
        if (not re.search(rf'(?m)^[ \t]*f32\s+{local}\s*;', prefix)
                or len(re.findall(rf'\b{local}\b', prefix)) != 2
                or re.search(rf'(?m)^\s*#\s*define\s+{local}\b', header + '\n' + part.clean)):
            return None
    before = prefix[:assignments[0].start()].rstrip()
    if (before[-1:] != ';'
            or any(prefix[left.end():right.start()].strip() for left, right in zip(assignments, assignments[1:]))
            or prefix[assignments[-1].end():].strip() or prefix.count('{') != prefix.count('}')
            or re.search(r'\b(?:goto|asm|__asm__|volatile)\b', prefix)):
        return None
    indent = hit['indent']
    replacement = ''.join(f'{indent}{local} = {local} * {local};\n' for local in names)
    replacement += f'{indent}{hit["call"]}({" + ".join(names)});'
    return edit(part.source, [(hit.start(), len(part.clean[:hit.end()].rstrip()), replacement)])


def variants(source, name, header, rows):
    changed = [index for index,(marker,_,_) in enumerate(rows) if marker != ' ']
    if not 1 <= len(changed) <= 9 or not (part := view(source,name)):
        return []
    if candidate := _square_vector_locals(part, header, rows, changed):
        return [('measured_square_vector_locals', candidate)]
    if len(changed) > 6:
        return []
    if candidate := sign_test(source,part,rows,changed):
        return [('measured_sign_test',candidate)]
    if candidate := field_after_advance(source,header,part,rows,changed):
        return [('measured_advanced_field',candidate)]
    if candidate := bounded_scale(source,part,rows):
        return [('measured_scaled_expression',candidate)]
    if candidate := staged_negation(source,part,rows,changed):
        return [('measured_staged_negation',candidate)]
    if candidate := _byte_lane_merge(part,header,rows,changed):
        return [('measured_byte_lane_merge',candidate)]
    if candidate := _branch_field_update(part, name, header, rows, changed):
        return [('measured_branch_field_update', candidate)]
    if candidate := _inline_rounded_shift(part, header, rows, changed):
        return [('measured_inline_rounded_shift', candidate)]
    return measured_branch_shapes.variants(part, name, header, rows, changed)
