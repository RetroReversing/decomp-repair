"""Recover ordered word snapshots stored as separate relocated halfwords."""

import re

from .csource import find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines
from .sdk_io_repairs import instructions

SCHEDULE = (
    ('load', 0, '$v0'), ('store', 0, '$v0'),
    ('load', 1, '$v0'), ('store', 1, '$v0'),
    ('load', 2, '$v1'), ('literal', 2, '$v0'),
    ('store', 3, '$v0'), ('store', 2, '$v1'),
    ('load', 3, '$v0'), ('store', 4, '$zero'),
    ('store', 5, '$zero'), ('return', 6, '$v0'),
)


def _target(asm):
    if asm.count('sh ') < 7 or 'lw' not in asm:
        return None
    lines = [' '.join(line.split()) for line in _lines(asm) if not line.startswith(('glabel ', 'endlabel '))]
    if len(lines) != 20:
        return None
    loads, stores, cursor, literal = {}, {}, 0, None
    for kind, slot, register in SCHEDULE:
        reg = re.escape(register)
        if kind == 'load':
            load = re.fullmatch(rf'lw {reg}, ({NUMBER})\(\$a0\)', lines[cursor])
            if not load:
                return None
            loads[slot] = integer(load[1])
            cursor += 1
        elif kind == 'literal':
            value = re.fullmatch(rf'addiu {reg}, \$zero, ({NUMBER})', lines[cursor])
            if not value:
                return None
            literal = integer(value[1])
            cursor += 1
        else:
            count = 3 if kind == 'return' else 2
            jump = 'jr $ra\n' if count == 3 else ''
            store = re.fullmatch(
                rf'lui \$at, %hi\((?P<base>{IDENT}) \+ (?P<offset>{NUMBER})\)\n{re.escape(jump)}'
                rf'sh {reg}, %lo\((?P=base) \+ (?P=offset)\)\(\$at\)',
                '\n'.join(lines[cursor:cursor + count]))
            if not store:
                return None
            stores[slot] = (store['base'], integer(store['offset']), cursor, cursor + count - 1)
            cursor += count
    return loads, stores, literal


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header='', resolve=None):
    if resolve is None or 'M2C_FIELD' not in source or not (target := _target(asm)):
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(void \*(?P<input>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature or '__repair_snapshot' in source + header:
        return None
    arg = signature['input']
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    statements = part.clean[start:end].split(';')
    if len(statements) != 8 or statements[-1].strip():
        return None
    source_updates = {}
    for statement in statements[:-1]:
        item = re.fullmatch(
            rf'\s*M2C_FIELD\(&(?P<base>{IDENT}), s16 \*, (?P<offset>{NUMBER})\) = '
            rf'(?:(?P<literal>{NUMBER})|\(s16\) M2C_FIELD\({arg}, s32 \*, (?P<load>{NUMBER})\))\s*', statement)
        if not item or (base := resolve(item['base'])) is None:
            return None
        address = base + integer(item['offset'])
        if address in source_updates:
            return None
        source_updates[address] = ('load', integer(item['load'])) if item['load'] else ('literal', integer(item['literal']))

    loads, stores, literal = target
    words = instructions(asm)
    if len(words) != 20:
        return None
    expected = [('load', loads[0]), ('load', loads[1]), ('load', loads[2]),
                ('literal', literal), ('literal', 0), ('literal', 0), ('load', loads[3])]
    aliases = []
    for slot, update in enumerate(expected):
        base_name, offset, high, low = stores[slot]
        base = resolve(base_name)
        if base is None:
            return None
        high_word, low_word = words[high], words[low]
        if high_word >> 16 != 0x3C01 or low_word >> 26 != 41 or (low_word >> 21) & 31 != 1:
            return None
        displacement = (low_word & 0x7FFF) - (low_word & 0x8000)
        address = (((high_word & 0xFFFF) << 16) + displacement) & 0xFFFFFFFF
        if address != base + offset or address % 2 or source_updates.get(address) != update:
            return None
        alias = f'D_{address:08X}'
        if resolve(alias) != address or alias in aliases or re.search(rf'\b{alias}\b', source + '\n' + header):
            return None
        aliases.append(alias)

    a, b, c, marker, clear_a, clear_b, d = aliases
    declarations = ''.join(f'extern s16 {alias};\n' for alias in aliases)
    body = f'''
    s32 __repair_snapshot0;
    s32 __repair_snapshot1;

    __repair_snapshot0 = *(s32 *)((char *){arg} + 0x{loads[0]:X});
    {a} = (s16) __repair_snapshot0;
    __repair_snapshot0 = *(s32 *)((char *){arg} + 0x{loads[1]:X});
    {b} = (s16) __repair_snapshot0;
    __repair_snapshot1 = *(s32 *)((char *){arg} + 0x{loads[2]:X});
    {marker} = 0x{literal:X};
    {c} = (s16) __repair_snapshot1;
    __repair_snapshot0 = *(s32 *)((char *){arg} + 0x{loads[3]:X});
    {clear_a} = 0;
    {clear_b} = 0;
    {d} = (s16) __repair_snapshot0;
'''
    definition = find(source, name)[0]
    return edit(source, [(definition, definition, declarations + '\n'), (start, end, body)])
