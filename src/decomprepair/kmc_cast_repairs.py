"""KMC casts supported by a measured load or read-modify-write mismatch."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .loaded_byte_repairs import complex_declarator, declarators
from .pattern_repairs import close

REGISTER = r'\$\w+'
ADDRESS = rf'(?:-?(?:0x[0-9a-f]+|\d+))?\({REGISTER}\)'
MEMORY = re.compile(rf'(lbu?|lhu?|lw|lwc1|sw)\s+({REGISTER}),\s*({ADDRESS})')
LUI = re.compile(rf'lui\s+({REGISTER}),\s*(0x[0-9a-f]+|\d+)')
OR = re.compile(rf'or\s+({REGISTER}),\s*({REGISTER}),\s*({REGISTER})')
BYTE_OPERAND = rf'(?:%lo\((?P<symbol>{IDENT})\)|(?:0x0|0)?)\({REGISTER}\)'
NARROW_LOAD = re.compile(rf'(?P<op>lbu|lhu|lb) (?P<reg>{REGISTER}), (?P<operand>{BYTE_OPERAND})')
RELOCATED = re.compile(rf'%hi\(({IDENT})\)')
CHAR_ARRAY = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>char)\s+(?P<symbol>{IDENT})\s*\[\s*\]\s*;')
TYPES = {'f32': 'lwc1', 'float': 'lwc1', 's32': 'lw', 'u32': 'lw', 'int': 'lw'}
WIDTHS = {'u8': 8, 'unsigned char': 8, 'u16': 16, 'unsigned short': 16}


def load_gaps(rows):
    """Find corresponding loads from the same address and the unwanted float conversion."""
    gaps = set()
    for i, (marker, target, candidate) in enumerate(rows):
        want, have = MEMORY.fullmatch(target), MEMORY.fullmatch(candidate)
        if (marker == ' ' or not want or not have or want[3] != have[3]
                or have[1] not in ('lb', 'lbu', 'lh', 'lhu')):
            continue
        if want[1] == 'lw':
            gaps.add('lw')
        elif want[1] == 'lwc1':
            following = [text for _, _, text in rows[i+1:i+6] if text]
            move = re.compile(rf'mtc1\s+{re.escape(have[2])},\s*({REGISTER})')
            for j, text in enumerate(following[:-1]):
                if (match := move.fullmatch(text)) and any(
                        re.fullmatch(rf'cvt\.s\.w\s+{REGISTER},\s*{re.escape(match[1])}', op)
                        for op in following[j+1:]):
                    gaps.add('lwc1')
                    break
    return gaps


def typed_loads(source, header, part, rows):
    gaps = load_gaps(rows)
    if not gaps:
        return []
    known = _blank(header) + '\n' + part.clean
    ctype = '|'.join(TYPES)
    assignment = re.compile(
        rf'(?m)^[ \t]*(?P<dest>{IDENT})\s*=\s*(?P<load>\(\s*(?P<type>{ctype})\s*\)\s*\*\s*(?P<ptr>{IDENT}))\s*;')
    by_kind = {}
    for match in assignment.finditer(part.body):
        typ, pointer, dest = match['type'], match['ptr'], match['dest']
        kind = TYPES[typ]
        if kind not in gaps or not re.search(
                rf'\b(?:u8|s8|u16|s16|char|short)\s*\*\s*{re.escape(pointer)}\s*;', part.body):
            continue
        if not re.search(rf'\b{typ}\s+{re.escape(dest)}\s*(?=[;=,)])', known):
            continue
        start, end = match.span('load')
        start, end = part.opening+1+start, part.opening+1+end
        if re.search(r'/[*/]', source[start:end]):
            continue
        replacement = f'*({typ} *){pointer}' + '\n' * source[start:end].count('\n')
        by_kind.setdefault(kind, []).append((pointer, (start, end, replacement)))
    eligible = [choices[0] for choices in by_kind.values() if len(choices) == 1]
    result = [('kmc_typed_load', edit(source, [change])) for _, change in eligible]
    if len(eligible) == 2 and eligible[0][0] == eligible[1][0]:
        # A single load change can improve the score, while two branches may
        # need their own type to recover the target together.
        result.insert(0, ('kmc_typed_load', edit(source, [change for _, change in eligible])))
    return result


def _array_read(part, context, named, relocated):
    hits = []
    for declaration in CHAR_ARRAY.finditer(part.clean, 0, part.opening):
        symbol = declaration['symbol']
        if symbol != named and (named or symbol not in relocated):
            continue
        if (len(declarators(context, symbol)) != 1 or complex_declarator(context, symbol)
                or re.search(rf'(?m)^\s*#\s*define\s+{symbol}\b', context)):
            continue
        # Other uses could require keeping the original array declaration.
        token = re.compile(rf'\b{symbol}\b')
        if len(token.findall(context)) != 2 or not (use := token.search(part.clean, part.opening + 1, part.end)):
            continue
        for load in re.finditer(r'\*\s*\(', part.clean[part.opening + 1:use.start()]):
            opening = part.opening + load.end()
            end = close(part.clean, opening)
            if end and end > use.start() and not re.match(r'\s*(?:=|[+\-*/%&|^]=|\+\+|--)', part.clean[end:]):
                hits.append((declaration, part.opening + 1 + load.start()))
                break
    return hits[0] if len(hits) == 1 else None


def _byte_immediate_register(wanted, actual):
    immediate = re.fullmatch(rf'addiu ({REGISTER}), \$zero, (?:0[xX][fF][fF]|255)', wanted)
    if immediate and re.fullmatch(rf'addiu {re.escape(immediate[1])}, \$zero, -(?:0x1|1)', actual):
        return re.escape(immediate[1])
    return None


def _unsigned_ff_store(part, context, rows, i):
    """Tie the positive byte literal to its original relocated byte store."""
    _, wanted, actual = rows[i]
    if not (reg := _byte_immediate_register(wanted, actual)):
        return None
    store = re.compile(rf'sb {reg}, %lo\(({IDENT})\)\({REGISTER}\)')
    return_slot = False
    for marker, op, previous in rows[i + 1:i + 5]:
        if marker == ' ' and op == previous and (hit := store.fullmatch(op)):
            symbol = hit[1]
            break
        if not return_slot and marker == ' ' and op == previous == 'jr $ra':
            return_slot = True
            continue
        if return_slot or re.match(rf'\w+\s+{reg}(?:,|$)|(?:[bj]\w*)\s', op):
            return None
    else:
        return None

    declaration = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>s8)\s+{symbol}\s*;')
    match = declaration.search(part.clean, 0, part.opening)
    assignment = re.findall(rf'\b{symbol}\s*=\s*({NUMBER})\s*;', part.body)
    if (not match or len(declarators(context, symbol)) != 1 or complex_declarator(context, symbol)
            or len(re.findall(rf'\b{symbol}\b', context)) != 2 or len(assignment) != 1
            or integer(assignment[0]) != 255):
        return None
    return (*match.span('type'), 'unsigned char')


def narrow_array_loads(source, header, part, rows, flags):
    """Recover an evidenced unsigned array load, keeping byte scaling for halfwords."""
    if 'char' not in source:
        return []
    changes = [i for i, (marker, _, _) in enumerate(rows) if marker != ' ']
    if not 1 <= len(changes) <= 2:
        return []
    for index in changes:
        wanted, actual = map(NARROW_LOAD.fullmatch, rows[index][1:])
        if (wanted and actual and wanted['op'] in ('lbu', 'lhu') and actual['op'] == 'lb'
                and (wanted['reg'], wanted['operand']) == (actual['reg'], actual['operand'])):
            break
    else:
        return []

    named = wanted['symbol']
    relocated = {symbol for _, target, _ in rows for symbol in RELOCATED.findall(target)}
    context = _blank(header) + '\n' + part.clean
    if not (read := _array_read(part, context, named, relocated)):
        return []
    declaration, at = read
    if wanted['op'] == 'lhu':
        if not named or len(changes) != 1 or '-fstrict-aliasing' in flags:
            return []
        return [('kmc_unsigned_halfword_array_load', edit(source, [(at + 1, at + 1, '(u16 *)')]))]

    edits = [(*declaration.span('type'), 'unsigned char')]
    if len(changes) == 2:
        other = next(i for i in changes if i != index)
        if not (literal := _unsigned_ff_store(part, context, rows, other)):
            return []
        edits.append(literal)
        return [('kmc_unsigned_byte_load_and_store', edit(source, edits))]
    return [('kmc_unsigned_byte_array', edit(source, edits))]


def missing_or_literals(rows):
    """Materialized high-word constants feeding a missing OR between a load and its store."""
    target = [(marker, text, candidate) for marker, text, candidate in rows if text]
    for i in range(1, len(target)-1):
        marker, instruction, candidate = target[i]
        if marker == ' ' or candidate or not (operation := OR.fullmatch(instruction)):
            continue
        load, store = (MEMORY.fullmatch(target[j][1]) for j in (i-1, i+1))
        if not (load and store and load[1] == 'lw' and store[1] == 'sw' and load[3] == store[3]
                and store[2] == operation[1] and load[2] in operation.groups()[1:]):
            continue
        constant = operation[3] if load[2] == operation[2] else operation[2]
        if constant == load[2]:
            continue
        for _, previous, _ in reversed(target[max(0, i-48):i-1]):
            if (upper := LUI.fullmatch(previous)) and upper[1] == constant:
                yield int(upper[2], 0) << 16
                break
            # A store or branch can end a local proof too. The matched example
            # keeps its upper immediate in a saved register across a direct call.
            if re.match(rf'\w+\s+{re.escape(constant)}(?:,|$)', previous):
                break
            if previous.startswith(('jal ', 'jalr ')) and not re.fullmatch(r'\$s[0-7]', constant):
                break


def truncated_literal(source, part, rows):
    literals = set(missing_or_literals(rows))
    if not literals:
        return []
    narrow = r'(?:u8|u16|unsigned\s+(?:char|short))'
    pattern = re.compile(rf'(?<!\|)\|(?!\|)\s*(?P<cast>\(\s*(?P<type>{narrow})\s*\)\s*)'
                         r'(?P<number>0[xX][\da-fA-F]+|[1-9]\d*)\b(?=\s*[);])')
    edits = []
    for match in pattern.finditer(part.body):
        value = int(match['number'], 0)
        width = WIDTHS[' '.join(match['type'].split())]
        if value not in literals or not 0 < value <= 0xffffffff or value & ((1 << width)-1):
            continue
        start, end = match.span('cast')
        start, end = part.opening+1+start, part.opening+1+end
        if re.search(r'/[*/]', source[start:end]):
            continue
        edits.append((start, end, '\n' * source[start:end].count('\n')))
    return [('kmc_truncated_literal', edit(source, edits))] if len(edits) == 1 else []


def byte_store_sites(rows):
    """Find byte destinations using the same immediate's low bits in both builds."""
    operand = rf'(%lo\(({IDENT})\)|-?(?:0x[\da-f]+|\d+))\({REGISTER}\)'
    sites = set()
    for i, (_, target, candidate) in enumerate(rows):
        if not (register := _byte_immediate_register(target, candidate)):
            continue
        byte_store = re.compile(rf'sb {register}, {operand}')
        delay_slot = False
        for marker, want, have in rows[i+1:i+6]:
            if marker != ' ' or want != have:
                break
            if sink := byte_store.fullmatch(want):
                address, name = sink.groups()
                sites.add(name if name else int(address, 0))
            elif not want.startswith(('lui ', 'j ')) or re.match(rf'lui {register},', want):
                break
            if delay_slot:
                break
            delay_slot = want.startswith('j ')
    return sites


def shared_byte_store_sites(rows):
    """Find a positive byte constant shared by multiple stores and a signed division."""
    positive = re.compile(rf'addiu ({REGISTER}), \$zero, (?:0[xX][fF][fF]|255)')
    negative = re.compile(rf'addiu ({REGISTER}), \$zero, -(?:0x1|1)')
    byte_store = re.compile(rf'sb ({REGISTER}), (-?(?:0x[\da-f]+|\d+))\({REGISTER}\)')
    division = re.compile(rf'div (?:\$zero, )?({REGISTER}), {REGISTER}')
    sites = set()
    for i, (_, want, have) in enumerate(rows):
        wanted, actual = positive.fullmatch(want), negative.fullmatch(have)
        if not wanted or not actual:
            continue
        shared = set()
        used_in_division = False
        for _, target, candidate in rows[i+1:]:
            if (div := division.fullmatch(target)) and div[1] == wanted[1]:
                used_in_division = True
            a, b = byte_store.fullmatch(target), byte_store.fullmatch(candidate)
            if (a and b and a[1] == wanted[1] and b[1] == actual[1]
                    and int(a[2], 0) == int(b[2], 0)):
                shared.add(int(a[2], 0))
        if used_in_division and len(shared) >= 2:
            sites.update(shared)
    return sites


def unsigned_byte_stores(source, header, part, rows):
    sites = byte_store_sites(rows) | shared_byte_store_sites(rows)
    if not sites:
        return []
    literal = r'(?:0[xX][fF][fF]|255)\s*;'
    field = re.compile(rf'\bM2C_FIELD\(\s*{IDENT}\s*,\s*(?P<type>s8)\s*\*\s*,\s*'
                       rf'(?P<offset>-?(?:0[xX][\da-fA-F]+|\d+))\s*\)\s*=\s*{literal}')
    fields = {}
    raw_field = re.compile(rf'\*\s*\(\s*(?P<type>s8)\s*\*\s*\)\s*[^;{{}}=\n]+?\+\s*'
                           rf'(?P<offset>-?(?:0[xX][\da-fA-F]+|\d+))\s*\)+\s*=\s*{literal}')
    for match in [*field.finditer(part.body), *raw_field.finditer(part.body)]:
        start, end = match.span('type')
        fields.setdefault(int(match['offset'], 0), []).append(
            (part.opening+1+start, part.opening+1+end, 'u8'))
    changes = [matches[0] for offset, matches in fields.items() if offset in sites and len(matches) == 1]

    clean_header = _blank(header) + '\n'
    known = clean_header + part.clean[:part.opening]
    context = clean_header + part.clean
    for symbol in sorted(site for site in sites if isinstance(site, str)):
        if (not re.search(rf'(?m)^\s*extern\s+s8\s+{symbol}\s*;', known)
                or len(declarators(context, symbol)) != 1):
            continue
        assignment = re.compile(rf'(?m)^[ \t]*(?P<symbol>{symbol})\s*=\s*{literal}')
        matches = list(assignment.finditer(part.body))
        if len(matches) == 1:
            start, end = matches[0].span('symbol')
            changes.append((part.opening+1+start, part.opening+1+end, f'*(u8 *)&{symbol}'))
    if not changes:
        return []
    return [('kmc_unsigned_byte_store', edit(source, changes))]


def variants(source, name, header, rows, flags=()):
    if not rows or not (part := view(source, name)) or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    stores = unsigned_byte_stores(source, header, part, rows)
    if re.search(r'\bvolatile\b', part.body):
        return stores
    result = [] if '-fstrict-aliasing' in flags else typed_loads(source, header, part, rows)
    return (result + truncated_literal(source, part, rows) + narrow_array_loads(source, header, part, rows, flags)
            + stores)


_FLOAT_LOOKUP = re.compile(
    rf'(?m)^sll (?P<index>{REGISTER}), (?P=index), (?:2|0x2)\n'
    rf'lui \$at, %hi\((?P<table>{IDENT})\)\naddu \$at, \$at, (?P=index)\n'
    r'jr \$ra\nlwc1 \$(?:f0|fv0), %lo\((?P=table)\)\(\$at\)$',
)


def _float_table(asm):
    if 'lwc1' not in asm or '%lo(' not in asm:
        return None
    from .measured_stack_drafts import _lines

    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    return _FLOAT_LOOKUP.search(text)


def float_table_applies(asm):
    return _float_table(asm) is not None


def rewrite_float_table(source, name, asm, header=''):
    """Restore the element type and scale the index once for a direct float load."""
    if 'M2C_UNK' not in source or not (target := _float_table(asm)):
        return None
    part = view(source, name)
    if not part or not re.search(rf'\bf32\s+{re.escape(name)}\s*\(\s*s32\s+{IDENT}\s*\)\s*$',
                                part.clean[:part.opening]):
        return None
    table = target['table']
    context = _blank(header) + '\n' + part.clean
    declaration = re.search(rf'\bextern\s+M2C_UNK\s+{table}\s*;', part.clean[:part.opening])
    if (not declaration or len(declarators(context, table)) != 1 or len(re.findall(rf'\b{table}\b', context)) != 2
            or complex_declarator(context, table)):
        return None
    terminal = re.search(rf'\breturn\s*(?P<lookup>\*\(&{table}\s*\+\s*'
                         rf'\((?P<index>{IDENT}|\({IDENT} & (?:0xFF|255)\))\s*\*\s*4\)\))\s*;\s*}}?\s*$',
                         part.body)
    if not terminal:
        return None
    a, b = terminal.span('lookup')
    at = part.opening + 1
    return edit(source, [(*declaration.span(), f'extern f32 {table}[];'),
                         (at + a, at + b, f'{table}[{terminal["index"]}]')])
