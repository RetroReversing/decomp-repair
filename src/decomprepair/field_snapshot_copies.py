"""Stage field copies in the order of a straight-line MIPS target."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines

REG = r'\$(?:v[01]|a[0-3]|t[0-9])'
RELOC = rf'(?P<symbol>{IDENT})(?: \+ (?:(?P<plain>{NUMBER})|\((?P<masked>{NUMBER}) & 0xFFFF\)))?'
HIGH = re.compile(rf'lui (?P<reg>\$at|{REG}), %hi\({RELOC}\)')
LOW = re.compile(rf'(?P<op>lw|sh|sw) (?P<reg>{REG}), %lo\({RELOC}\)\((?P<base>\$at|{REG})\)')
LOAD = re.compile(rf'(?P<op>lw|lhu) (?P<reg>{REG}), (?P<offset>{NUMBER})?\((?P<base>{REG})\)')
PREFIX = '__repair_field_snapshot'
FIELD = 'M2C_FIELD'


def _address(match):
    return match['symbol'], integer(match['plain'] or match['masked'] or '0')


def _relocation(high, low, op):
    top, bottom = HIGH.fullmatch(high), LOW.fullmatch(low)
    if top and bottom and bottom['op'] == op and top['reg'] == bottom['base'] and _address(top) == _address(bottom):
        return bottom
    return None


def _schedule(asm):
    if 'lui' not in asm or '%hi(' not in asm or not ('lhu' in asm or 'lw' in asm):
        return None
    lines = [' '.join(line.split()) for line in _lines(asm) if not line.startswith(('glabel ', 'endlabel '))]
    if not 7 <= len(lines) <= 21 or lines[-2] != 'jr $ra':
        return None

    pointer = _relocation(*lines[:2], 'lw')
    if pointer and pointer['reg'] != pointer['base']:
        return None
    base = pointer['reg'] if pointer else '$a0'
    read, write, kind, width = ('lhu', 'sh', 'u16', 2) if pointer else ('lw', 'sw', 's32', 4)
    lines = lines[2 if pointer else 0:-2] + lines[-1:]

    pending, loads, stores, sequence = {}, {}, {}, []
    base_replaced = False
    i = 0
    while i < len(lines):
        if load := LOAD.fullmatch(lines[i]):
            reg, offset = load['reg'], integer(load['offset'] or '0')
            if load['op'] != read or load['base'] != base or base_replaced or reg in pending or offset % width:
                return None
            base_replaced = reg == base
            slot = len(loads)
            loads[slot] = offset
            pending[reg] = slot
            sequence.append(('load', slot))
            i += 1
        else:
            store = _relocation(*lines[i:i + 2], write) if i + 1 < len(lines) else None
            if not store or store['base'] != '$at' or store['reg'] not in pending:
                return None
            slot = pending.pop(store['reg'])
            stores[slot] = _address(store)
            sequence.append(('store', slot))
            i += 2
    if (pending or not 2 <= len(loads) <= 6 or len(set(loads.values())) != len(loads)
            or len(set(stores.values())) != len(stores) or sequence[-1][0] != 'store'):
        return None
    if all(sequence[i][0] != sequence[i + 1][0] for i in range(len(sequence) - 1)):
        return None
    return kind, _address(pointer) if pointer else None, loads, stores, sequence


def applies(asm):
    return _schedule(asm) is not None


def rewrite(source, name, asm, header=''):
    """Bind each loaded value to its original store before moving either operation."""
    if FIELD not in source or PREFIX in source + header or not (schedule := _schedule(asm)):
        return None
    part = view(source, name)
    if not part:
        return None

    kind, pointer, loads, stores, sequence = schedule
    parameters = 'void' if pointer else rf'void\s*\*\s*(?P<arg>{IDENT})'
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*{parameters}\s*\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    base = (rf'{FIELD}\(&(?P<pointer>{IDENT}), void \*\*, (?P<ptr_off>{NUMBER})\)' if pointer
            else re.escape(signature['arg']))
    assignment = re.compile(
        rf'\s*(?P<dest>{FIELD}\(&(?P<symbol>{IDENT}), {kind} \*, (?P<offset>{NUMBER})\))\s*=\s*'
        rf'(?P<value>(?:\({kind}\) )?{FIELD}\({base}, {kind} \*, (?P<field>{NUMBER})\))\s*'
    )

    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    parts = part.clean[start:end].split(';')
    if len(parts) != len(loads) + 1 or parts[-1].strip():
        return None

    updates = {}
    for line in parts[:-1]:
        match = assignment.fullmatch(line)
        if not match or (pointer and (match['pointer'], integer(match['ptr_off'])) != pointer):
            return None
        address = match['symbol'], integer(match['offset'])
        if address in updates:
            return None
        updates[address] = match
    if any(dest not in updates or integer(updates[dest]['field']) != loads[slot] for slot, dest in stores.items()):
        return None

    declarations = [f'    {kind} {PREFIX}{slot};' for slot in loads]
    lines = declarations + ['']
    for operation, slot in sequence:
        update = updates[stores[slot]]
        local = f'{PREFIX}{slot}'
        if operation == 'load':
            lines.append(f"    {local} = {update['value']};")
        else:
            lines.append(f"    {update['dest']} = {local};")
    return edit(source, [(start, end, '\n' + '\n'.join(lines) + '\n')])
