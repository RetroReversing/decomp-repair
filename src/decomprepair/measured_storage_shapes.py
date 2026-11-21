"""Measured MIPS pointer and return-value storage repairs."""

import re

from . import measured_relocated_lifetimes
from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, calls, edit, integer, view
from .mips_returns import instructions

REG = r'\$[a-z][a-z0-9]*'
FIELD = rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*void\s*\*\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\)'
WORD = r'(?:s32|u32)'


def variants(source, name, header, rows, asm, *, big_endian):
    changed = [i for i, (marker, _, _) in enumerate(rows) if marker != ' ']
    if len(changed) == 1 and big_endian:
        label, candidate = 'wide_sdk_return_store', _wide_return(source, name, header, rows, asm, changed[0])
    elif len(changed) == 2:
        label, candidate = 'staged_pointer_advance', _pointer_advance(source, name, rows, changed)
    elif len(changed) == 3:
        label, candidate = 'cursor_after_word_copy', _cursor(source, name, rows, changed)
    else:
        return measured_relocated_lifetimes.variants(source, name, header, rows, asm, changed)
    return [(label, candidate)] if candidate else []


def _pointer_advance(source, name, rows, changed):
    add, store = changed
    if add < 3 or store != add + 2 or store != len(rows) - 1 or rows[add + 1][1] != 'jr $ra':
        return None
    advance = re.fullmatch(rf'addiu (?P<dest>{REG}), (?P<old>{REG}), (?P<step>{NUMBER})', rows[add][1])
    if not advance:
        return None
    dest, old, step = advance.groups()
    saved = re.fullmatch(rf'sw {re.escape(dest)}, (?P<slot>{NUMBER})\((?P<context>{REG})\)', rows[store][1])
    if (not saved or dest == old or rows[add][2] != f'addiu {old}, {old}, {step}'
            or rows[store][2] != f"sw {old}, {saved['slot']}({saved['context']})"
            or rows[add - 1][1] != f"lw {old}, {saved['slot']}({saved['context']})"
            or not re.fullmatch(rf'sw {REG}, {NUMBER}\({re.escape(dest)}\)', rows[add - 2][1])):
        return None
    part = view(source, name)
    if not part:
        return None
    block = part.clean[part.opening + 1:part.end].rstrip()
    update = re.search(
        rf'(?m)^(?P<indent>[ \t]*)(?P<field>{FIELD})\s*=\s*\(void\s*\*\)\s*'
        rf'\(\s*(?P=field)\s*\+\s*(?P<step>{NUMBER})\s*\);\s*}}$', block)
    if (not update or integer(update['offset']) != integer(saved['slot'])
            or integer(update['step']) != integer(step)):
        return None
    field = update['field']
    locals_ = list(re.finditer(rf'(?m)^[ \t]*(?P<temporary>{IDENT})\s*=\s*{re.escape(field)}\s*;',
                               block[:update.start()]))
    if len(locals_) != 1:
        return None
    local = locals_[0]['temporary']
    before = block[:locals_[0].start()]
    between = block[locals_[0].end():update.start()]
    if (not re.search(rf'\bvoid\s*\*\s*{local}\s*;', before)
            or re.search(rf'&\s*{local}\b', block)
            or re.search(rf'\b{local}\s*=', between)
            or not re.search(rf'(?m)^\s*M2C_FIELD\(\s*{local}\s*,[^;\n]+\)\s*=', between)):
        return None
    opening = part.opening + 1
    stop = opening + block.index(';', update.end('step')) + 1
    original_field = source[opening + update.start('field'):opening + update.end('field')]
    replacement = (f"{update['indent']}{local} = {original_field} + {update['step']};\n"
                   f"{update['indent']}{original_field} = {local};")
    return edit(source, [(opening + update.start(), stop, replacement)])


def _cursor(source, name, rows, changed):
    zero, load, copy = changed
    move = re.fullmatch(r'move (?P<dest>\$a[0-3]), (?P<base>\$a[0-3])', rows[copy][1])
    reset = rows[zero][1]
    if (not move or move['base'] == move['dest'] or load != zero + 2 or copy != load + 1
            or not re.fullmatch(r'move \$t[0-9], \$zero', reset)
            or rows[zero][2] != move[0] or rows[copy][2] != reset):
        return None
    read = re.fullmatch(rf'lw (?P<value>{REG}), (?P<offset>{NUMBER})\({re.escape(move["base"])}\)', rows[load][1])
    if (not read or rows[load][2] != f"lw {read['value']}, {read['offset']}({move['dest']})"
            or not re.fullmatch(rf'sw {re.escape(read["value"])}, {NUMBER}\({REG}\)', rows[zero + 1][1])
            or not any(re.fullmatch(rf'lw {REG}, {NUMBER}\({re.escape(move["dest"])}\)', row[1])
                       for row in rows[copy + 1:copy + 6])):
        return None
    part = view(source, name)
    if not part:
        return None
    pair = re.compile(
        rf'(?m)^(?P<bind>[ \t]*(?P<local>{IDENT})\s*=\s*(?P<base>{IDENT})\s*;)'
        rf'(?P<gap>[ \t]*\n)(?P<copy>[ \t]*M2C_FIELD\([^;\n]+\)\s*=\s*'
        rf'(?:\({WORD}\)\s*)?M2C_FIELD\(\s*(?P=base)\s*,\s*{WORD}\s*\*,\s*(?P<offset>{NUMBER})\s*\);)')
    for match in pair.finditer(part.clean, part.opening + 1, part.end):
        local = match['local']
        prefix = part.clean[part.opening + 1:match.start()]
        if (integer(match['offset']) != integer(read['offset']) or prefix.rstrip()[-1:] not in (';', '{')
                or not re.search(rf'\bvoid\s*\*\s*{local}\s*;', prefix)
                or len(re.findall(rf'\b{local}\b', prefix)) != 1
                or re.search(rf'\b{local}\b', match['copy'])):
            continue
        return edit(source, [(*match.span('bind'), source[slice(*match.span('copy'))]),
                             (*match.span('copy'), source[slice(*match.span('bind'))])])
    return None


def _wide_return(source, name, header, rows, asm, low):
    target, candidate = rows[low][1:]
    if (low < 5 or not target.startswith('sw $v1, ') or candidate != target.replace('$v1,', '$v0,', 1)
            or re.search(r'\bosGetTime\s*\(', _blank(header))):
        return None
    # osGetTime returns the 64-bit timer. Both return registers reach paired
    # big-endian word stores, with only address setup between the call and stores.
    ops = [' '.join(row.split()) for row in instructions(asm)]
    if len(ops) != len(rows) or ops[low - 5:low - 3] != ['jal osGetTime', 'nop']:
        return None
    store = re.compile(rf'sw \$v(?P<reg>[01]), %lo\((?P<base>{IDENT})\s*\+\s*(?P<offset>{NUMBER})\)\(\$at\)')
    high_slot, low_slot = store.fullmatch(ops[low - 2]), store.fullmatch(ops[low])
    if not high_slot or not low_slot or high_slot['reg'] != '0' or low_slot['reg'] != '1':
        return None
    base, high_offset, low_offset = high_slot['base'], integer(high_slot['offset']), integer(low_slot['offset'])
    if low_slot['base'] != base or low_offset != high_offset + 4:
        return None
    for at, slot in ((low - 3, high_slot), (low - 1, low_slot)):
        if not re.fullmatch(rf'lui \$at, %hi\({base}\s*\+\s*{slot["offset"]}\)', ops[at]):
            return None
    part = view(source, name)
    if not part or len(list(calls(part, 'osGetTime'))) != 1:
        return None
    prototype = re.search(r'(?m)^[ \t]*(?P<type>s32|M2C_UNK)\s+osGetTime\s*\(\s*\)\s*;(?=[ \t]*/\* extern \*/)',
                          source[:part.opening])
    match = re.search(
        rf'(?m)^(?P<indent>[ \t]*)(?P<local>{IDENT})\s*=\s*osGetTime\(\);\s*\n[ \t]*'
        rf'M2C_FIELD\(\s*&{base}\s*,\s*s32\s*\*,\s*(?P<high>{NUMBER})\)\s*=\s*(?P=local);\s*\n[ \t]*'
        rf'M2C_FIELD\(\s*&{base}\s*,\s*u32\s*\*,\s*(?P<low>{NUMBER})\)\s*=\s*\(u32\)\s*\(u64\)\s*(?P=local);',
        part.clean[part.opening + 1:part.end])
    if not prototype or not match or (integer(match['high']), integer(match['low'])) != (high_offset, low_offset):
        return None
    local = match['local']
    decl = re.search(rf'(?m)^[ \t]*(?:s32|M2C_UNK)\s+{local}\s*;[ \t]*\n', part.body[:match.start()])
    if not decl or len(re.findall(rf'\b{local}\b', part.body)) != 4:
        return None
    opening = part.opening + 1
    replacement = f"{match['indent']}M2C_FIELD(&{base}, long long *, {match['high']}) = osGetTime();"
    return edit(source, [(prototype.start('type'), prototype.end(), 'long long osGetTime(void);'),
                         (opening + decl.start(), opening + decl.end(), ''),
                         (opening + match.start(), opening + match.end(), replacement)])
