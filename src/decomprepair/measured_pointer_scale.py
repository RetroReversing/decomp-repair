"""Test duplicated pointer scaling against measured MIPS shifts and byte steps."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, view
from .pattern_repairs import close

WRITE_SUFFIX = re.compile(r'\s*(?:=(?!=)|(?:[-+*/%&|^]|<<|>>)=|\+\+|--)')
SHIFT = re.compile(rf'sll\s+(\$\w+),\s*(\$\w+),\s*({NUMBER})')


def _word_shifts(rows):
    hits = []
    for row, (mark, target, current) in enumerate(rows):
        if mark == ' ':
            continue
        wanted, staged = SHIFT.fullmatch(target), SHIFT.fullmatch(current)
        if wanted and staged and wanted.groups()[:2] == staged.groups()[:2]:
            amount = integer(wanted[3])
            if 1 <= amount <= 29 and integer(staged[3]) == amount + 2:
                hits.append((row, wanted[1], amount))
    return hits


def _float_table(part, name, header, rows):
    signature = re.search(rf'\bf32\s+{re.escape(name)}\(s32 (?P<index>{IDENT})\)\s*$', part.clean[:part.opening])
    body = re.fullmatch(
        rf'\s*return \*\(&(?P<base>{IDENT}) \+ \(\(\((?P<index>{IDENT}) \+ (?P<offset>{NUMBER})\) '
        rf'& (?P<mask>{NUMBER})\) \* 4\)\);\s*', part.body.rstrip('}\n '))
    if signature and body and signature['index'] == body['index'] and integer(body['mask']) == 255:
        offset = f'({body["index"]} + {body["offset"]})'
    else:
        signature = re.search(rf'\bf32\s+{re.escape(name)}\s*\(\s*f32\s+({IDENT})\s*\)\s*$',
                              part.clean[:part.opening])
        cast_index = rf'\(s32\)\s*(?P<index>{IDENT})'
        address = rf'\s*return\s*\*\(&(?P<base>{IDENT})\s*\+\s*\(\('
        tail = rf'\s*&\s*(?P<mask>{NUMBER})\)\s*\*\s*4\)\)\s*;\s*'
        statement = part.body.rstrip('}\n ')
        body = re.fullmatch(address + cast_index + tail, statement)
        if not body:
            body = re.fullmatch(
                address + rf'\((?P<biased>{cast_index}\s*[+-]\s*{NUMBER})\)' + tail, statement)
        if not signature or not body or signature[1] != body['index']:
            return None
        offset = f'(s32){body["index"]}'
        if bias := body.groupdict().get('biased'):
            offset = f'({bias})'
    base = body['base']
    decl = re.search(rf'\bextern M2C_UNK {base};', part.clean[:part.opening])
    if (not decl or re.search(rf'\b{base}\b', header) or len(re.findall(rf'\b{base}\b',part.clean)) != 2
            or not any(re.fullmatch(rf'lwc1\s+\$\w+,\s*%lo\({base}\)\(\$\w+\)', wanted) for _, wanted, _ in rows)
            or not any(re.fullmatch(r'cvt\.s\.w\s+\$\w+,\s*\$\w+', current) for _,_,current in rows)):
        return None
    end = len(part.clean[:part.end].rstrip()) - 1
    replacement = f"\n    return {base}[{offset} & {body['mask']}];\n"
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


def _scale_bases(rows, row, register, side=1):
    """Find word loads using the shifted register and a corroborating table relocation."""
    code = [entry[side] for entry in rows]
    index = re.escape(register)
    high = re.compile(rf'lui (?P<base>\$\w+), %hi\((?P<name>{IDENT})\)')
    result = set()
    for i in range(row + 1, len(code) - 2):
        if hit := high.fullmatch(code[i]):
            base, name = re.escape(hit['base']), hit['name']
            if re.fullmatch(rf'addu {base}, {base}, {index}', code[i + 1]):
                immediate = re.fullmatch(rf'lw \$\w+, %lo\({name}\)\({base}\)', code[i + 2])
                call_slot = (i + 3 < len(code) and re.fullmatch(rf'jal {IDENT}', code[i + 2])
                             and re.fullmatch(rf'lw \$a[0-3], %lo\({name}\)\({base}\)', code[i + 3]))
                if immediate or call_slot:
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


def _inline_scale(part, header, symbols, kind='M2C_UNK', width=4, byte_shift=None):
    product = rf'\((?P<value>.+) \* (?P<scale>{NUMBER})\)'
    patterns = (
        re.compile(rf'&(?P<table>{IDENT}) \+ {product}', re.S),
        re.compile(rf'{product} \+ &(?P<table>{IDENT})', re.S),
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
        scale = integer(hit['scale'])
        if width > 1 and scale != width and byte_shift is None:
            continue
        if byte_shift is not None and scale & -scale != 1 << byte_shift:
            continue
        table = hit['table']
        declaration = _read_declaration(part, header, table, 1)
        if declaration and not re.search(r'/[*/]', part.source[deref.start():end]):
            if width == 2 and scale != width:
                # The odd part of the byte stride also survives in the target.
                value = hit['value']
                if close(f'({value})', 0) != len(value) + 2:
                    continue
                if not re.fullmatch(IDENT, value):
                    value = f'({value})'
                text = f'*({kind} *)({table} + {value} * {hit["scale"]})'
                declared_type = 'u8'
            else:
                index = hit['value'] if width > 1 else f'{hit["value"]} * {hit["scale"]}'
                text, declared_type = f'{table}[{index}]', kind
            matches.append([(*declaration.span(), f'extern {declared_type} {table}[];'), (deref.start(), end, text)])
    return edit(part.source, matches[0]) if len(matches) == 1 else None


def _repeated_word_table(part, header, rows, shifts):
    """Require two measured 4-to-16-byte accesses to the same relocated word table."""
    tables = {}
    for row, register, amount in shifts:
        if amount != 2:
            continue
        shared = _scale_bases(rows, row, register) & _scale_bases(rows, row, register, side=2)
        for table in shared:
            tables[table] = tables.get(table, 0) + 1
    candidates = []
    for table, count in sorted(tables.items()):
        if count < 2:
            continue
        refs = []
        prefix = re.compile(rf'\*\(\s*&{re.escape(table)}\s*\+\s*\(')
        for access in prefix.finditer(part.clean, part.opening + 1, part.end):
            end = close(part.clean, access.end() - 1)
            if not end:
                continue
            index = re.fullmatch(r'(.+?)\s*\*\s*(?:4|0x4)\s*', part.clean[access.end():end - 1], re.S)
            outer_close = re.match(r'\s*\)', part.clean[end:part.end])
            if not index or not outer_close or re.search(r'[;{}=]|\+\+|--', index[1]):
                continue
            stop = end + outer_close.end()
            if WRITE_SUFFIX.match(part.clean, stop) or re.search(r'/[*/]', part.source[access.start():stop]):
                continue
            refs.append((access.start(), stop, f'{table}[{index[1]}]'))
        if len(refs) < 2 or not (declaration := _read_declaration(part, header, table, len(refs))):
            continue
        replacement = (*declaration.span(), f'extern M2C_UNK {table}[];')
        candidates.append(('measured_repeated_word_table', edit(part.source, [replacement, *refs])))
        if len(candidates) == 2:
            break
    return candidates


def _relocated_scaled_load(part, header, rows, row, register, amount):
    """A reproduced address adds one shifted index to matching hi/lo base relocations."""
    # A scheduled return-address spill can separate the shift from the address calculation.
    if row + 1 < len(rows):
        mark, wanted, current = rows[row + 1]
        if mark == ' ' and wanted == current and re.fullmatch(rf'sw \$ra, {NUMBER}\(\$sp\)', wanted):
            rows = rows[:row + 1] + rows[row + 2:]
    changed = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changed) not in (2, 3) or changed[0] != row or changed[-1] not in (row + 3, row + 4):
        return None
    if len(changed) == 3 and changed[1] != row + 1:
        return None
    load_row = changed[-1]
    high, low = [], []
    for side in (1, 2):
        addend = r'(?:\+(?:0x2|2))?' if side == 2 else ''
        if not (base := re.fullmatch(
            rf'lui (\$\w+), %hi\(({IDENT})({addend})\)', rows[row + 1][side]
        )):
            return None
        if not re.fullmatch(rf'addu {re.escape(base[1])}, {re.escape(base[1])}, {re.escape(register)}',
                            rows[row + 2][side]):
            return None
        if load_row == row + 4:
            preceding = rows[row + 3][side]
            if preceding != 'jr $ra' and not re.fullmatch(rf'jal {IDENT}', preceding):
                return None
        if not (load := re.fullmatch(
            rf'(lh|lhu|lb|lbu) (\$\w+), %lo\({base[2]}{re.escape(base[3])}\)\({re.escape(base[1])}\)', rows[load_row][side]
        )):
            return None
        high.append(base.groups())
        low.append(load.groups())
    if high[0][0] != high[1][0] or low[0] != low[1]:
        return None
    if high[1][2] and high[0][1] != high[1][1]:
        return None
    kind, width = {'lh': ('s16', 2), 'lhu': ('u16', 2), 'lb': ('s8', 1), 'lbu': ('u8', 1)}[low[0][0]]
    if width == 1 and (amount < 2 or high[1][2]):
        return None
    return _inline_scale(part, header, {high[0][1]}, kind, width, byte_shift=amount)


def _halfword_scans(source, name, rows):
    """Remove explicit byte scaling from two sentinel reads through one typed pointer."""
    changes = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(changes) != 2:
        return None
    bases = set()
    for row in changes:
        if row < 1 or row + 3 >= len(rows):
            return None
        target, current = (SHIFT.fullmatch(text) for text in rows[row][1:])
        if (not target or not current or target.groups()[:2] != current.groups()[:2]
                or integer(target[3]) != 1 or integer(current[3]) != 2):
            return None
        register = re.escape(target[1])
        clip, add, load, branch = (rows[i][1] for i in (row - 1, row + 1, row + 2, row + 3))
        if not re.fullmatch(rf'andi {re.escape(target[2])}, \$\w+, (?:65535|0x[fF]{{4}})', clip):
            return None
        if not (base := re.fullmatch(rf'addu {register}, {register}, (\$a[0-3])', add)):
            return None
        if not (value := re.fullmatch(rf'lhu (\$\w+), (?:0|0x0)?\({register}\)', load)):
            return None
        loop = re.fullmatch(rf'b(?:eq|ne)l? {re.escape(value[1])}, \$\w+, ({NUMBER})', branch)
        if not loop or integer(loop[1]) % 4 or integer(loop[1]) // 4 > row - 1:
            return None
        bases.add(base[1])
    if bases != {'$a0'} or not (part := view(source, name)):
        return None
    signature = rf'\b{re.escape(name)}\(\s*u16\s*\*\s*(?P<base>{IDENT})\s*[,)]\s*[^{{}};]*$'
    where = re.search(signature, part.clean[:part.opening])
    if not where:
        return None
    pointer = where['base']
    pattern = re.compile(rf'\*\(\(\((?P<index>{IDENT} & (?:0x[fF]{{4}}|65535))\) \* (?:2|0x2)\) \+ {pointer}\)')
    refs = list(pattern.finditer(part.clean, part.opening + 1, part.end))
    if len(refs) != len(changes) or len({ref['index'] for ref in refs}) != 1:
        return None
    if any(not re.match(r'\s*(?:==|!=)', part.clean[ref.end():]) for ref in refs):
        return None
    return edit(source, [(*ref.span(), f'*(({ref["index"]}) + {pointer})') for ref in refs])



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


def _loop_step(source, name, rows):
    """Correct a typed cursor when its only mismatch is the scaled delay-slot advance."""
    changed = [(i, a, b) for i, (kind, a, b) in enumerate(rows) if kind != ' ']
    if len(changed) != 1:
        return None
    index, target, candidate = changed[0]
    step = re.compile(r'addiu (?P<reg>\$\w+), (?P=reg), (?P<step>-?(?:0x[0-9a-fA-F]+|[0-9]+))')
    wanted, current = step.fullmatch(target), step.fullmatch(candidate)
    if not wanted or not current or wanted['reg'] != current['reg'] or wanted['reg'] in ('$sp', '$zero'):
        return None
    byte_step, scaled_step = ((-1 if val.startswith('-') else 1) * integer(val.lstrip('-'))
                              for val in (wanted['step'], current['step']))
    if not byte_step or scaled_step not in (2 * byte_step, 4 * byte_step) or index < 2:
        return None
    branch = re.fullmatch(rf'b(?:nez|eqz|gtz|gez|ltz|lez) \$\w+, ({NUMBER})', rows[index-1][1])
    if not branch:
        return None
    start, misalignment = divmod(integer(branch[1]), 4)
    if misalignment or start >= index - 1:
        return None
    width = scaled_step // byte_step
    load, store = (r'lh[u]?', 'sh') if width == 2 else ('lw', 'sw')
    operand = rf'\$\w+, (?:0|0x0)?\({re.escape(wanted["reg"])}\)'
    loop = [a for _, a, _ in rows[start:index-1]]
    if not (any(re.fullmatch(rf'{load} {operand}', a) for a in loop)
            and any(re.fullmatch(rf'{store} {operand}', a) for a in loop)):
        return None

    if not (part := view(source, name)):
        return None
    bits = width * 8
    operator = r'\+=' if byte_step > 0 else '-='
    updates = []
    for hit in re.finditer(rf'(?m)^\s*(?P<ptr>{IDENT})\s*{operator}\s*(?P<step>{NUMBER})\s*;', part.body):
        if integer(hit['step']) != abs(byte_step) or byte_step % width:
            continue
        ptr = hit['ptr']
        declaration = rf'[su]{bits}\s*\*\s*{ptr}\b'
        if len(re.findall(rf'(?m)^\s*{declaration}\s*;', part.body[:hit.start()])) != 1:
            continue
        if not re.search(rf'(?m)^\s*\*\s*{ptr}\s*[+\-*/%&|^]?=(?!=)', part.body[:hit.start()]):
            continue
        if re.search(rf'&\s*{ptr}\b', part.body):
            continue
        start, end = hit.span('step')
        offset = part.opening + 1
        updates.append((offset + start, offset + end, str(abs(byte_step) // width)))
    return edit(source, updates) if len(updates) == 1 else None


def _under_scaled_halfword_cursor(source, name, rows):
    """A byte cursor advances by an element count inside a halfword-reading loop."""
    if 'char *' not in source or '+=' not in source:
        return None
    advances = []
    target = []
    previous = ''
    step = re.compile(rf'addiu (\$\w+), \1, ({NUMBER})')
    back_edge = re.compile(rf'bnez \$\w+, ({NUMBER})(?: \[bytes [0-9a-f]+\])?')
    for mark, wanted, current in rows:
        if not wanted:
            continue
        if (mark != ' ' and (a := step.fullmatch(wanted)) and (b := step.fullmatch(current))
                and a[1] == b[1] and a[1] not in ('$sp', '$zero')
                and 0 < integer(b[2]) <= 32 and integer(a[2]) == 2 * integer(b[2])
                and (branch := back_edge.fullmatch(previous))):
            start, remainder = divmod(integer(branch[1]), 4)
            halfword = re.compile(rf'lh[u]? \$\w+, (?:0|0x0)?\({re.escape(a[1])}\)')
            if not remainder and start < len(target) - 1 and any(halfword.fullmatch(op) for op in target[start:]):
                advances.append((integer(b[2]), integer(a[2])))
        target.append(wanted)
        previous = wanted
    if len(advances) != 1 or not (part := view(source, name)):
        return None
    current, wanted = advances[0]
    edits = []
    for hit in re.finditer(rf'(?m)^\s*char\s*\*\s*({IDENT})\s*;', part.body):
        pointer = hit[1]
        assignment = rf'\b{pointer}\s*=\s*\(*\s*\*\s*\([su]16\s*\*\*\)'
        use = rf'\*\s*\([su]16\s*\*\)\s*{pointer}\b'
        if not re.search(assignment, part.body) or not re.search(use, part.body):
            continue
        for update in re.finditer(rf'(?m)^\s*{pointer}\s*\+=\s*({NUMBER})\s*;', part.body):
            if integer(update[1]) == current:
                offset = part.opening + 1
                edits.append((offset + update.start(1), offset + update.end(1), str(wanted)))
    return edit(source, edits) if len(edits) == 1 else None


def _call_byte_offset(source, name, rows):
    """A halfword read and a displaced pointer feed different arguments of the same call."""
    mismatches = [i for i, (mark, _, _) in enumerate(rows) if mark != ' ']
    if len(mismatches) != 1 or (i := mismatches[0]) < 2:
        return None
    add = re.compile(rf'addiu \$a1, \$a1, ({NUMBER})')
    target, candidate = (add.fullmatch(op) for op in rows[i][1:])
    call = re.fullmatch(rf'jal ({IDENT})', rows[i - 1][1])
    if (not target or not candidate or not call or rows[i - 1][1] != rows[i - 1][2]
            or not 0 < integer(target[1]) or integer(candidate[1]) != 2 * integer(target[1])
            or not any(a == b and re.fullmatch(r'lhu \$a2, (?:0|0x0)?\(\$a1\)', a)
                       for _, a, b in rows[max(0, i - 4):i - 1])):
        return None
    if not (part := view(source, name)):
        return None
    parameters = re.search(rf'\b{re.escape(name)}\s*\([^,()]+,\s*u16\s*\*\s*({IDENT})\s*\)\s*$',
                           part.clean[:part.opening])
    if not parameters:
        return None
    pointer = parameters[1]
    body = re.fullmatch(
        rf'\s*{call[1]}\([^,;{{}}]+,\s*(?P<address>{pointer}\s*\+\s*(?P<offset>{NUMBER}))'
        rf'\s*,\s*\*\s*{pointer}\s*\)\s*;\s*', part.body.rstrip('}\n '))
    if not body or integer(body['offset']) != integer(target[1]):
        return None
    a, b = (part.opening + 1 + at for at in body.span('address'))
    if source[a:b] == body['address']:
        return edit(source, [(a, b, f'(u8 *){body["address"]}')])
    return None


def variants(source, name, header, rows):
    if candidate := _call_byte_offset(source, name, rows):
        return [('measured_call_byte_offset', candidate)]
    if candidate := _under_scaled_halfword_cursor(source, name, rows):
        return [('measured_halfword_byte_cursor', candidate)]
    if ('+=' in source or '-=' in source) and (candidate := _loop_step(source, name, rows)):
        return [('measured_pointer_step', candidate)]
    if '* 2' in source and 'u16 *' in source and (candidate := _halfword_scans(source, name, rows)):
        return [('measured_halfword_scan_scale', candidate)]
    if 'extern M2C_UNK ' not in source or not (shifts := _word_shifts(rows)):
        return []
    part = view(source, name)
    if part is None:
        return []
    if len(shifts) > 1:
        return _repeated_word_table(part, header, rows, shifts)
    row, register, amount = shifts[0]
    if sum(mark != ' ' for mark, _, _ in rows) == 1 and amount >= 2 and (bases := _scale_bases(rows, row, register)):
        candidate = _inline_scale(part, header, bases) if amount == 2 else _shared_shift(part, header, bases, amount)
        if candidate:
            return [('measured_duplicate_word_scale', candidate)]
    if candidate := _relocated_scaled_load(part, header, rows, row, register, amount):
        return [('measured_relocated_array_scale', candidate)]
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
