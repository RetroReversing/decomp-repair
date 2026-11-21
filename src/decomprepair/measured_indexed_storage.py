"""Measured ordering and byte scaling for KMC address calculations."""

import re

from . import passthrough_argument_repairs
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_address_repairs import _offset_pairs
from .pattern_repairs import close

S32_FIELD = rf'M2C_FIELD\(&{IDENT}, s32 \*, {NUMBER}\)'


def _guarded_counter(part, header, rows, asm):
    local = '__repair_counter_address'
    if len(rows) != 32 or local in part.source + header:
        return None
    target = [row[1] for row in rows]
    if ([row[2] for row in rows[:6]] != [target[i] for i in (2, 3, 0, 1, 5, 4)]
            or any(row[0] != ' ' for row in rows[6:]) or target[6] != 'slt $v0, $a0, $a1'
            or not target[7].startswith('beqz $v0, ') or target[8] != 'nop'
            or not target[9].startswith('bltzl $a0, ') or target[10] != 'sw $zero, ($v1)'
            or target[13] != 'lw $v1, ($v1)' or target[21] != 'sw $v1, ($a2)'):
        return None
    fields = re.search(
        rf'(?m)^(?P<pad>[ \t]*)if \((?P<counter>{S32_FIELD}) < (?P<position>{S32_FIELD})\) (?P<brace>{{)\n'
        rf'(?P=pad)    if \((?P=counter) < 0\) {{\s*(?P=counter) = 0;\s*}}',
        part.body)
    if not fields or fields['counter'] == fields['position']:
        return None
    # The disassembler can show either the containing symbol and offset or
    # the exact relocated address. Bind the C fields using the original asm.
    _, addresses = _offset_pairs(asm)
    for register, key in (('$v1', 'counter'), ('$a2', 'position')):
        expression = re.fullmatch(rf'M2C_FIELD\(&({IDENT}), s32 \*, ({NUMBER})\)', fields[key])
        symbol = expression[1]
        if ((register, symbol, integer(expression[2])) not in addresses
                or re.search(rf'\bvolatile\b[^;{{}}\n]*\b{symbol}\b',
                             _blank(header) + part.clean[:part.opening])):
            return None
    begin = part.opening + 1
    arm = close(part.clean, begin + fields.start('brace'), '{', '}')
    if not arm:
        return None
    tail = part.clean[begin + fields.end():arm - 1]
    copy = list(re.finditer(rf'(?m)^\s*{re.escape(fields["position"])} = (?:\(s32\) )?'
                            rf'(?P<read>{re.escape(fields["counter"])});', tail))
    if len(copy) != 1 or tail[copy[0].end():].strip():
        return None
    return edit(part.source, [
        (begin, begin, f'\n{fields["pad"]}s32 *{local};'),
        (begin + fields.start('counter'), begin + fields.end('position'),
         f'{fields["position"]} > {fields["counter"]}'),
        (begin + fields.end('brace') + 1, begin + fields.end('brace') + 1,
         f'{fields["pad"]}    {local} = &{fields["counter"]};\n'),
        (begin + fields.end() + copy[0].start('read'), begin + fields.end() + copy[0].end('read'), f'*{local}'),
    ])


_BYTE_BASE = re.compile(
    rf'lui \$v1, %hi\((?P<base>{IDENT})\)\nlw \$v1, %lo\((?P=base)\)\(\$v1\)\n'
    rf'sll \$a1, \$a0, (?P<shift1>[0-4])\naddu \$a1, \$a1, \$a0\nsll \$a1, \$a1, (?P<shift2>[0-4])\n'
    rf'addiu \$v0, \$zero, -?{NUMBER}\naddu \$v1, \$v1, \$a1\nsb \$v0, (?P<first>{NUMBER})\(\$v1\)\n'
    r'lui \$v0, %hi\((?P=base)\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)'
)


def _first_byte_base(part, header, rows):
    local = '__repair_first_store_base'
    if (not 15 <= len(rows) <= 80 or local in part.source + header
            or [i for i, row in enumerate(rows) if row[0] != ' '] != [0, 3]
            or rows[0][1] or rows[3][2] or rows[0][2] != rows[3][1]):
        return None
    target = [row[1] for row in rows if row[1]]
    match = _BYTE_BASE.fullmatch('\n'.join(target[:10]))
    if not match:
        return None
    base = match['base']
    if (re.search(rf'\bvolatile\b[^;{{}}\n]*\b{base}\b', _blank(header) + part.clean[:part.opening])
            or re.search(r'\b(?:volatile|restrict)\b', part.body)
            or not re.search(rf'(?m)^[ \t]*extern s32 {base};', part.clean[:part.opening])):
        return None
    source = re.match(
        rf'\n(?P<pad>[ \t]+)s32 (?P<index>{IDENT});\s*(?P=index) = (?P<formal>{IDENT}) \* (?P<scale>{NUMBER});\s*'
        rf'M2C_FIELD\(\((?P<base>{base}) \+ (?P=index)\), s8 \*, (?P<first>{NUMBER})\) = -?{NUMBER};\s*'
        rf'M2C_FIELD\(\({base} \+ (?P=index)\), s8 \*, {NUMBER}\) = -?{NUMBER};',
        part.body)
    stride = ((1 << int(match['shift1'])) + 1) << int(match['shift2'])
    if (not source or integer(source['scale']) != stride or integer(source['first']) != integer(match['first'])
            or not re.search(rf'\(s32 {source["formal"]}\)\s*$', part.clean[:part.opening])):
        return None
    start = part.opening + 1
    location = start + source.end('index') + 1
    return edit(part.source, [
        (location, location, f'\n{source["pad"]}s32 {local} = {base};'),
        (start + source.start('base'), start + source.end('base'), local),
    ])


_RELOCATED_WORD = re.compile(
    rf'(?:(?:addiu \$v0, \$zero, (?P<small>{NUMBER})|lui \$v0, (?P<high>{NUMBER})\n'
    rf'ori \$v0, \$v0, (?P<low>{NUMBER}))\n)'
    rf'lui \$at, %hi\((?P<symbol>{IDENT})\)\naddu \$at, \$at, \$v1\n'
    r'sw \$v0, %lo\((?P=symbol)\)\(\$at\)\n'
)


def _relocated_words(part, header, rows, asm):
    if not 20 <= len(rows) <= 80 or 'M2C_UNK' not in part.source:
        return None
    scale = re.fullmatch(r'sll \$v1, \$a0, ([1-9]|[12][0-9])', rows[2][1])
    if not scale:
        return None
    shift = int(scale[1])
    if rows[2][2] != f'sll $a0, $a0, {shift + 2}':
        return None
    target = '\n'.join(row[1] for row in rows[3:])
    end = re.search(rf'(?m)^jal (?P<callee>{IDENT})\nmove \$a1, \$zero\n', target)
    if not end:
        return None
    stores = list(_RELOCATED_WORD.finditer(target, 0, end.start()))
    if (not 3 <= len(stores) <= 12 or ''.join(match[0] for match in stores) != target[:end.start()]
            or len({match['symbol'] for match in stores}) != len(stores)):
        return None
    changed = [tuple(row[1:]) for row in rows[3:] if row[0] != ' ']
    if changed != [('addu $at, $at, $v1', 'addu $at, $at, $a0')] * len(stores) + [
            ('move $a1, $zero', 'move $a0, $zero')]:
        return None
    callee = end['callee']
    if not passthrough_argument_repairs._entry_a0_reaches(asm, callee):
        return None
    external = _blank(header)
    prototype = re.search(rf'(?m)^[ \t]*M2C_UNK {callee}\((?P<type>M2C_UNK)\);[ \t]*/\* extern \*/',
                          part.source[:part.opening])
    assignment = re.match(rf'\s*s32 (?P<index>{IDENT});\s*(?P=index) = (?P<arg>{IDENT}) << (?P<shift>{NUMBER});',
                          part.body)
    if (not prototype or not assignment or integer(assignment['shift']) != shift
            or re.search(rf'\b{callee}\b', external)
            or not re.search(rf'\(s32 {assignment["arg"]}\)\s*$', part.clean[:part.opening])):
        return None
    index = assignment['index']
    remaining = part.body[assignment.end():]
    position = part.opening + 1 + assignment.end()
    updates = [(*prototype.span('type'), 's32, s32')]
    for store in stores:
        symbol = store['symbol']
        declaration = re.search(rf'(?m)^[ \t]*extern (?P<type>M2C_UNK) {symbol};', part.clean[:part.opening])
        statement = re.match(rf'\s*(?P<lhs>\*\(&{symbol} \+ {index}\)) = (?P<value>{NUMBER});', remaining)
        value = integer(store['small']) if store['small'] else (integer(store['high']) << 16) | integer(store['low'])
        if not declaration or not statement or integer(statement['value']) != value or re.search(rf'\b{symbol}\b', external):
            return None
        updates.extend([(*declaration.span('type'), 's32'),
                        (position + statement.start('lhs'), position + statement.end('lhs'),
                         f'*(s32 *)((u8 *)&{symbol} + {index})')])
        remaining = remaining[statement.end():]
        position += statement.end()
    call = re.fullmatch(rf'\s*{callee}\((?P<value>0)\);\s*}}?\s*', remaining)
    if not call:
        return None
    at = position + call.start('value')
    return edit(part.source, [*updates, (at, at, f'{assignment["arg"]}, ')])


def variants(source, name, header, rows, asm):
    if 'M2C_FIELD' not in source and 'M2C_UNK' not in source:
        return []
    if not (part := view(source, name)):
        return []
    if candidate := _guarded_counter(part, header, rows, asm):
        return [('guarded_counter_address', candidate)]
    if candidate := _first_byte_base(part, header, rows):
        return [('first_indexed_byte_base', candidate)]
    if candidate := _relocated_words(part, header, rows, asm):
        return [('relocated_indexed_word_stores', candidate)]
    return []
