"""Use a two-bit MIPS shift discrepancy to test a duplicated word scale."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view

SHIFT = re.compile(rf'sll\s+(\$\w+),\s*(\$\w+),\s*({NUMBER})')


def _word_shift(rows):
    hits = []
    for mark, target, current in rows:
        if mark == ' ':
            continue
        wanted, staged = SHIFT.fullmatch(target), SHIFT.fullmatch(current)
        if wanted and staged and wanted.groups()[:2] == staged.groups()[:2]:
            if integer(wanted[3]) == 2 and integer(staged[3]) == 4:
                hits.append(wanted[1])
    return len(hits) == 1


def _float_table(part, name, header, rows):
    signature = re.search(rf'\bf32\s+{re.escape(name)}\(s32 (?P<index>{IDENT})\)\s*$', part.clean[:part.opening])
    body = re.fullmatch(
        rf'\s*return \*\(&(?P<base>{IDENT}) \+ \(\(\((?P<index>{IDENT}) \+ (?P<offset>{NUMBER})\) '
        rf'& (?P<mask>{NUMBER})\) \* 4\)\);\s*', part.body.rstrip('}\n '))
    if not signature or not body or signature['index'] != body['index'] or integer(body['mask']) != 255:
        return None
    base = body['base']
    decl = re.search(rf'\bextern M2C_UNK {base};', part.clean[:part.opening])
    if (not decl or re.search(rf'\b{base}\b', header) or len(re.findall(rf'\b{base}\b',part.clean)) != 2
            or not any(re.fullmatch(rf'lwc1\s+\$\w+,\s*%lo\({base}\)\(\$\w+\)', wanted) for _, wanted, _ in rows)
            or not any(re.fullmatch(r'cvt\.s\.w\s+\$\w+,\s*\$\w+', current) for _,_,current in rows)):
        return None
    end = len(part.clean[:part.end].rstrip()) - 1
    replacement = f"\n    return {base}[({body['index']} + {body['offset']}) & {body['mask']}];\n"
    return edit(part.source,[(decl.start(),decl.end(),f'extern f32 {base}[];'),(part.opening+1,end,replacement)])


def _stride(part, header):
    pattern = re.compile(rf'(?m)^    (?P<local>{IDENT}) = (?P<index>{IDENT}) \* (?P<stride>{NUMBER});')
    for hit in pattern.finditer(part.clean, part.opening+1, part.end):
        stride = integer(hit['stride'])
        if not 0 < stride <= 0x10000 or stride % 4:
            continue
        local = hit['local']
        if not re.search(rf'\bs32 {local};',part.body):
            continue
        uses = re.findall(rf'\*\(&({IDENT}) \+ {local}\)', part.body)
        if not uses or len(set(uses)) != len(uses) or len(re.findall(rf'\b{local}\b',part.body)) != len(uses)+2:
            continue
        if any(not re.search(rf'\bextern M2C_UNK {symbol};', part.clean[:part.opening])
               or re.search(rf'\b{symbol}\b', header) for symbol in uses):
            continue
        return (*hit.span('stride'),str(stride//4))
    return None


def _stage_call(part, rows):
    changed = [wanted for mark,wanted,_ in rows if mark != ' ']
    if not any(re.fullmatch(r'andi \$v[01], \$a2, (?:1|0x1)', op) for op in changed):
        return None
    if not any(re.fullmatch(r'addu \$a2, \$a2, \$v[01]', op) for op in changed):
        return None
    pattern = re.compile(rf'(?m)^    (?P<call>{IDENT}\([^;\n]+, )(?P<value>{IDENT}) \+ \((?P=value) & 1\)\);')
    for hit in pattern.finditer(part.clean, part.opening+1, part.end):
        value = hit['value']
        if (value not in {decl['name'] for decl in locals_for(part)}
                or re.search(rf'\b{value}\b', hit['call'])):
            continue
        if not re.search(rf'(?m)^    {value} = M2C_FIELD\({IDENT}, s32 \*, {NUMBER}\);\s*$',
                         part.clean[part.opening+1:hit.start()]):
            continue
        replacement = f"    {value} = {value} + ({value} & 1);\n    {hit['call']}{value});"
        return (*hit.span(),replacement)
    return None


def variants(source, name, header, rows):
    if 'extern M2C_UNK ' not in source or not _word_shift(rows):
        return []
    part = view(source, name)
    if part is None:
        return []
    if candidate := _float_table(part, name, header, rows):
        return [('measured_float_table_scale', candidate)]
    stride = _stride(part, header)
    if not stride:
        return []
    result = [('measured_word_stride', edit(source, [stride]))]
    if stage := _stage_call(part, rows):
        result.insert(0, ('measured_word_stride_call', edit(source, [stride, stage])))
    return result
