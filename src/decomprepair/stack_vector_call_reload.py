"""Recover a three-float snapshot across two calls using the same stack output."""
import re

from .integer_repair_support import IDENT, edit, split_args, view
from .mips_returns import instructions

FAMILY = 'stack_vector_call_reload'
_OVERLAY = re.compile(
    r'\s*union\s*\{\s*unsigned char bytes\[\d+\];(?P<members>.*?)'
    r'\}\s*m2c_initial_frame\s*;', re.S,
)
_MEMBER = re.compile(
    r'\s*struct\s*\{\s*(?:unsigned char pad\[(\d+)\];\s*)?'
    r'f32 value;\s*\}\s*(view_sp[0-9A-Fa-f]+);',
)
_CALL = re.compile(rf'\s*(?P<callee>{IDENT})\((?P<args>[^;{{}}]+)\)\s*;')
_LOAD = re.compile(r'lwc1\s+(\$\w+),\s*(0x[\da-fA-F]+|\d+)\(\$sp\)')


def _target(asm, base, argument, expected):
    code = instructions(asm)
    calls = [(i, line.split()[1]) for i, line in enumerate(code) if re.fullmatch(rf'jal\s+{IDENT}', line)]
    if len(calls) < 2:
        return False
    (first, callee), (second, repeat) = calls[-2:]
    if callee != repeat or callee != expected or second - first > 12:
        return False
    address = re.compile(rf'addiu\s+\$a{argument},\s*\$sp,\s*(0x[\da-fA-F]+|\d+)')
    for call, start in ((first, max(0, first - 6)), (second, first + 2)):
        if not any((hit := address.fullmatch(line)) and int(hit[1], 0) == base
                   for line in code[start:call + 2]):
            return False
    saved = [_LOAD.fullmatch(line) for line in code[second - 3:second]]
    after = code[second + 2:second + 11]
    if len(saved) != 3 or not all(saved) or len(after) != 9:
        return False
    registers = {row[1] for row in saved}
    if len(registers) != 3 or not all(re.fullmatch(r'\$(?:fs[0-5]|f(?:2[02468]|30))', register)
                                          for register in registers):
        return False
    if any(re.match(r'(?:b\w*|j\w*)\b', line) for line in code[first + 2:second]):
        return False
    output = None
    for i, prior in enumerate(saved):
        load, subtract, store = after[i * 3:i * 3 + 3]
        later = _LOAD.fullmatch(load)
        if not later or later[1] in registers or int(prior[2], 0) != base + 4*i or int(later[2], 0) != base + 4*i:
            return False
        if not re.fullmatch(rf'sub\.s\s+{re.escape(prior[1])},\s*{re.escape(prior[1])},\s*{re.escape(later[1])}', subtract):
            return False
        dest = re.fullmatch(rf'swc1\s+{re.escape(prior[1])},\s*(0x[\da-fA-F]+|\d+)\((\$\w+)\)', store)
        if not dest or int(dest[1], 0) != 4*i or (output and dest[2] != output):
            return False
        output = dest[2]
    return True


def _args(text):
    return [text[start:end].strip() for start, end in split_args(text)]


def variants(source, name, asm):
    part = view(source, name)
    if not part or '__repair_vector_before' in part.clean:
        return []
    body = part.body[:part.body.rfind("}")]
    overlay = _OVERLAY.match(body)
    if not overlay:
        return []
    remainder = overlay['members']
    members = []
    while remainder.strip():
        member = _MEMBER.match(remainder)
        if not member:
            return []
        members.append((int(member[1] or 0), member[2]))
        remainder = remainder[member.end():]
    if len(members) != 3 or [offset for offset, _ in members] != [0, 4, 8]:
        return []
    fields = [f'm2c_initial_frame.{field}.value' for _, field in members]
    base = int(members[0][1][7:], 16)
    if [int(field[7:], 16) for _, field in members] != [base, base+4, base+8]:
        return []
    first = _CALL.match(body, overlay.end())
    second = first and _CALL.match(body, first.end())
    if not second or first['callee'] != second['callee']:
        return []
    args = _args(first['args'])
    new_args = _args(second['args'])
    if len(args) != len(new_args) or len(args) > 4 or args.count('&'+fields[0]) != 1:
        return []
    arg = args.index('&'+fields[0])
    if new_args[arg] != args[arg] or sum('m2c_initial_frame' in a for a in args + new_args) != 2:
        return []
    tail = body[second.end():].strip()
    stores = tail.split(';')
    if len(stores) != 4 or stores[-1] or not _target(asm, base, arg, first["callee"]):
        return []
    copies = [f'__repair_vector_before_{i}' for i in range(3)]
    destination = None
    for i, field in enumerate(fields):
        occurrence = f'{field} - {field}'
        store = re.fullmatch(
                rf'M2C_FIELD\(({IDENT}),\s*f32\s*\*,\s*{4*i}\)\s*=\s*\(f32\)\s*\({re.escape(occurrence)}\)',
                stores[i].strip())
        if not store or (destination and store[1] != destination):
            return []
        destination = store[1]
        tail = tail.replace(occurrence, f'{copies[i]} - {field}', 1)
    start = part.opening + 1
    declarations = '\n    f32 ' + ', '.join(copies) + ';'
    capture = ''.join(f'\n    {copy} = {field};' for copy, field in zip(copies, fields))
    changes = [(start, start, declarations),
               (start+first.end(), start+first.end(), capture),
               (start+second.end(), start+len(body), '\n    '+tail+'\n')]
    return [(FAMILY, edit(source, changes))]
