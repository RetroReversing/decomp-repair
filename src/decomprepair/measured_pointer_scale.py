"""Use a two-bit MIPS shift discrepancy to test a duplicated word scale."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view
from .pattern_repairs import close

WRITE_SUFFIX = re.compile(r'\s*(?:=(?!=)|(?:[-+*/%&|^]|<<|>>)=|\+\+|--)')
SHIFT = re.compile(rf'sll\s+(\$\w+),\s*(\$\w+),\s*({NUMBER})')


def _word_shift(rows):
    hits = []
    for row, (mark, target, current) in enumerate(rows):
        if mark == ' ':
            continue
        wanted, staged = SHIFT.fullmatch(target), SHIFT.fullmatch(current)
        if wanted and staged and wanted.groups()[:2] == staged.groups()[:2]:
            amount = integer(wanted[3])
            if 2 <= amount <= 29 and integer(staged[3]) == amount + 2:
                hits.append((row, wanted[1], amount))
    return hits[0] if len(hits) == 1 else None


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


def _scale_bases(rows, row, register):
    """Find word loads using the shifted register and a corroborating table relocation."""
    code = [target for _, target, _ in rows]
    index = re.escape(register)
    high = re.compile(rf'lui (?P<base>\$\w+), %hi\((?P<name>{IDENT})\)')
    result = set()
    for i in range(row + 1, len(code) - 2):
        if hit := high.fullmatch(code[i]):
            base, name = re.escape(hit['base']), hit['name']
            if (re.fullmatch(rf'addu {base}, {base}, {index}', code[i + 1])
                    and re.fullmatch(rf'lw \$\w+, %lo\({name}\)\({base}\)', code[i + 2])):
                result.add(name)
                if hit['base'] == register:
                    break
        if re.match(rf'(?:[bj]\w*|\w+ {index},)\s', code[i]):
            break

    if row + 2 < len(code):
        add = re.fullmatch(rf'addu {index}, {index}, (?P<base>\$\w+)', code[row + 1])
        if add and re.fullmatch(rf'lw \$\w+, (?:0|0x0)?\({index}\)', code[row + 2]):
            base = re.escape(add['base'])
            for i in range(row - 1, 0, -1):
                if not re.match(rf'\w+ {base},', code[i]):
                    continue
                bind = high.fullmatch(code[i - 1])
                if (bind and bind['base'] == add['base']
                        and re.fullmatch(rf'addiu {base}, {base}, %lo\({bind["name"]}\)', code[i])):
                    result.add(bind['name'])
                break
    return result


def _read_declaration(part, header, symbol, uses):
    found = re.search(rf'\bextern M2C_UNK {symbol};', part.clean[:part.opening])
    if (not found or re.search(rf'\b{symbol}\b', header)
            or len(re.findall(rf'\b{symbol}\b', part.clean)) != uses + 1):
        return None
    return found


def _inline_scale(part, header, symbols):
    patterns = (
        re.compile(rf'&(?P<table>{IDENT}) \+ \((?P<value>.+) \* (?:4|0x4)\)', re.S),
        re.compile(rf'\((?P<value>.+) \* (?:4|0x4)\) \+ &(?P<table>{IDENT})', re.S),
    )
    matches = []
    for deref in re.compile(r'\*\(').finditer(part.clean, part.opening + 1, part.end):
        end = close(part.clean, deref.end() - 1)
        if not end or WRITE_SUFFIX.match(part.clean, end):
            continue
        address = part.clean[deref.end():end - 1]
        hit = next((match for pattern in patterns if (match := pattern.fullmatch(address))), None)
        if not hit or hit['table'] not in symbols or re.search(r'[;{}=]|\+\+|--', hit['value']):
            continue
        table = hit['table']
        declaration = _read_declaration(part, header, table, 1)
        if declaration and not re.search(r'/[*/]', part.source[deref.start():end]):
            matches.append([(*declaration.span(), f'extern M2C_UNK {table}[];'),
                            (deref.start(), end, f'{table}[{hit["value"]}]')])
    return edit(part.source, matches[0]) if len(matches) == 1 else None


def _shared_shift(part, header, symbols, amount):
    pattern = re.compile(rf'(?m)^\s*(?P<offset>{IDENT}) = \({IDENT} & (?:255|0xFF)\) << (?P<amount>{NUMBER});')
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        offset = hit['offset']
        if integer(hit['amount']) != amount or not re.search(rf'\bs32 {offset};', part.body):
            continue
        refs = list(re.finditer(rf'\*\(&(?P<table>{IDENT}) \+ {offset}\)', part.body))
        if any(WRITE_SUFFIX.match(part.body, ref.end()) for ref in refs):
            continue
        names = [ref['table'] for ref in refs]
        if not names or set(names) != symbols or len(set(names)) != len(names):
            continue
        if len(re.findall(rf'\b{offset}\b', part.body)) != len(refs) + 2:
            continue
        decls = [_read_declaration(part, header, table, 1) for table in names]
        if not all(decls):
            continue
        edits = [(*hit.span('amount'), str(amount - 2))]
        start = part.opening + 1
        for table, decl, ref in zip(names, decls, refs):
            edits.extend([(*decl.span(), f'extern M2C_UNK {table}[];'),
                          (start + ref.start(), start + ref.end(), f'{table}[{offset}]')])
        return edit(part.source, edits)
    return None


def variants(source, name, header, rows):
    if 'extern M2C_UNK ' not in source or not (shift := _word_shift(rows)):
        return []
    part = view(source, name)
    if part is None:
        return []
    row, register, amount = shift
    if sum(mark != ' ' for mark, _, _ in rows) == 1 and (bases := _scale_bases(rows, row, register)):
        candidate = _inline_scale(part, header, bases) if amount == 2 else _shared_shift(part, header, bases, amount)
        if candidate:
            return [('measured_duplicate_word_scale', candidate)]
    if amount != 2:
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
