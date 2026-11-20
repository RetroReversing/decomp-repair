"""Recover a record loop when m2c drops byte views of a MIPS unaligned copy."""

import re

from .integer_repair_support import IDENT, NUMBER, integer, view
from .mips import abi_register_names

MEMORY = re.compile(rf'(\w+)\s+(\$\w+),\s*({NUMBER})?\((\$\w+)\)')
DECLARATIONS = re.compile(rf'\s*(M2C_UNK|s32|u32|u16|void)\s+(\*\s*)?({IDENT})\s*;')
PARAMETER = re.compile(rf'\bvoid\s+{IDENT}\s*\(\s*u16\s*\*\s*({IDENT})\s*\)\s*$')
BOUND = re.compile(rf'(?:(?P<plain>{IDENT})|M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*u8\s*\*\s*,\s*(?P<offset>{NUMBER})\s*\))')
DRAFT = re.compile(rf'''
    (?P<out>{IDENT})\s*=\s*(?P<arg>{IDENT})\s*;
    \s*(?P<input>{IDENT})\s*=\s*&\s*(?P<source>{IDENT})(?:\s*\+\s*(?P<source_offset>{NUMBER}))?\s*;
    \s*(?P<index>{IDENT})\s*=\s*0\s*;
    \s*if\s*\(\s*\(s32\)\s*(?P<bound>{BOUND.pattern})\s*>\s*0\s*\)\s*\{{
    \s*(?P<bytes>{IDENT})\s*=\s*(?P=arg)\s*\+\s*3\s*;
    \s*do\s*\{{
    \s*(?P<word>sp[0-9A-F]+)\s*=\s*M2C_UNALIGNED32\(M2C_FIELD\((?P=input),\s*M2C_UNK\s*\*,\s*0\)\)\s*;
    \s*(?P<half>sp[0-9A-F]+)\s*=\s*M2C_UNALIGNED32\(M2C_FIELD\((?P=input),\s*M2C_UNK\s*\*,\s*4\)\)\s*;
    \s*(?P<status>{IDENT})\s*=\s*\(u32\)\s*\(\s*(?P<flag>sp[0-9A-F]+)\s*&\s*(?P<mask>{NUMBER})\s*\)
        \s*>>\s*(?P<shift>{NUMBER})\s*;
    \s*M2C_FIELD\((?P=bytes),\s*s8\s*\*,\s*1\)\s*=\s*\(s8\)\s*(?P=status)\s*;
    \s*if\s*\(\s*(?P=status)\s*==\s*0\s*\)\s*\{{
    \s*\*(?P=out)\s*=\s*(?P=half)\s*;
    \s*M2C_FIELD\((?P=bytes),\s*u8\s*\*,\s*-1\)\s*=\s*(?P<first>sp[0-9A-F]+)\s*;
    \s*M2C_FIELD\((?P=bytes),\s*u8\s*\*,\s*0\)\s*=\s*(?P<second>sp[0-9A-F]+)\s*;
    \s*}}
    \s*(?P=index)\s*\+=\s*1\s*;
    \s*(?P=input)\s*\+=\s*8\s*;
    \s*(?P=bytes)\s*\+=\s*6\s*;
    \s*(?P=out)\s*\+=\s*6\s*;
    \s*}}\s*while\s*\(\s*(?P=index)\s*<\s*\(s32\)\s*(?P=bound)\s*\)\s*;
    \s*}}\s*
    ''', re.X)


def stack_copy(asm):
    """(stack offset, input register) for a fixed-frame eight-byte copy with overlapping reloads."""
    if not all(op in asm for op in ('lwl', 'lwr', 'swl', 'swr')):
        return None
    lines = [re.sub(r'/\*.*?\*/|#.*', '', line).strip() for line in abi_register_names(asm).splitlines()]
    lines = [line for line in lines if line]
    adjustments = re.findall(rf'(?m)^addiu\s+\$sp,\s*\$sp,\s*(-?{NUMBER})$', '\n'.join(lines))
    if len(adjustments) != 2:
        return None
    opening, closing = adjustments
    if not opening.startswith("-") or closing.startswith("-"):
        return None
    frame, restore = -integer(opening[1:]), integer(closing)
    if frame >= 0 or restore != -frame:
        return None
    copies = []
    for index, line in enumerate(lines):
        if not line.startswith('lwl') or index+8 >= len(lines):
            continue
        memory = [MEMORY.fullmatch(line) for line in lines[index:index+9]]
        if not all(memory):
            continue
        ops, registers, offsets, bases = zip(*(match.groups() for match in memory))
        at = [integer(offset or '0') for offset in offsets]
        slot = at[4]
        if (ops != ('lwl', 'lwr', 'lwl', 'lwr', 'swl', 'swr', 'swl', 'swr', 'lbu')
                or at != [0, 3, 4, 7, slot, slot+3, slot+4, slot+7, slot+2]
                or slot % 2 or not 0 <= slot <= -frame-8
                or len(set(bases[:4])) != 1 or bases[0] == '$sp' or set(bases[4:]) != {'$sp'}
                or registers[:4] != registers[4:8] or registers[:4] != (registers[0],)*2+(registers[2],)*2
                or registers[0] == registers[2] or bases[0] in registers[:4]):
            continue
        reloads = {(m[1], integer(m[3] or '0')) for line in lines[index+9:]
                   if (m := MEMORY.fullmatch(line)) and m[4] == '$sp'}
        advance = re.compile(rf'addiu\s+{re.escape(bases[0])},\s*{re.escape(bases[0])},\s*({NUMBER})')
        if ({('lhu', slot+4), ('lbu', slot+6), ('lbu', slot+7)} <= reloads
                and any(integer(hit[1]) == 8 for line in lines[index+9:] if (hit := advance.fullmatch(line)))):
            copies.append((slot, bases[0]))
    return copies[0] if len(copies) == 1 else None


def _bound(match, asm, source, context, resolve):
    if match['plain']:
        return '', match['plain']
    # Keep the counter a distinct C object when the target reloads it by an absolute
    # relocation. Sharing its base with the copy cursor lets KMC hoist that address.
    base, offset = match['base'], integer(match['offset'])
    if resolve is not None and (address := resolve(base)) is not None and 0 <= address+offset <= 0xFFFFFFFF:
        relocation = re.compile(rf'\blbu\s+\$\w+,\s*%lo\(\s*{base}\s*\+\s*({NUMBER})\s*\)')
        if sum(integer(hit[1]) == offset for hit in relocation.finditer(asm)) >= 2:
            alias = f'D_{address+offset:08X}'
            if not re.search(rf'\b{alias}\b', source+'\n'+context) and resolve(alias) == address+offset:
                return f'extern u8 {alias};\n', alias
    return '', match['bound']


def rewrite(source, name, asm, context='', resolve=None):
    """Return compilable C for the witnessed m2c record loop, or leave the draft alone."""
    if source.count('M2C_UNALIGNED32(') != 2 or not (copy := stack_copy(asm)):
        return None
    part = view(source, name)
    if part is None:
        return None
    signature = PARAMETER.search(part.clean[:part.opening])
    if signature is None or re.search(r'__m2c_unaligned_\w+', source+'\n'+context):
        return None
    declarations = {}
    cursor = part.opening+1
    while decl := DECLARATIONS.match(part.clean, cursor):
        if decl[3] in declarations:
            return None
        declarations[decl[3]] = decl[1]+('*' if decl[2] else '')
        cursor = decl.end()
    ending = len(part.clean[:part.end].rstrip()) - 1
    match = DRAFT.fullmatch(part.clean[cursor:ending].lstrip())
    if match is None or match['arg'] != signature[1]:
        return None
    required = {match['word']: 'M2C_UNK', match['half']: 'u16', match['out']: 'u16*',
                match['index']: 's32', match['status']: 'u32', match['bytes']: 'void*'}
    if (len(required) != 6 or declarations.get(match['input']) not in ('void*', 'M2C_UNK*')
            or declarations != required | {match['input']: declarations[match['input']]}):
        return None
    slot, _ = copy
    if [int(match[k][2:], 16) for k in ('word', 'flag', 'half', 'first', 'second')] != [
            slot, slot+2, slot+4, slot+6, slot+7]:
        return None
    if not 0 <= integer(match['mask']) <= 0xFF or not 0 <= integer(match['shift']) <= 7:
        return None
    extra, bound = _bound(match, asm, source, context, resolve)
    address = f"(u8 *)&{match['source']}"
    if match['source_offset']:
        address += f" + {match['source_offset']}"
    return (source[:signature.start()]+extra+
            f"""struct __m2c_unaligned_output {{ u16 __m2c_unaligned_half0; u8 __m2c_unaligned_byte2; u8 __m2c_unaligned_byte3; u8 __m2c_unaligned_byte4; }};
{source[signature.start():part.opening].strip()} {{
    struct __m2c_unaligned_output *__m2c_unaligned_out = (struct __m2c_unaligned_output *){signature[1]};
    u8 *__m2c_unaligned_src = {address};
    struct __m2c_unaligned_input {{
        u8 __m2c_unaligned_padding[2];
        u8 __m2c_unaligned_byte2;
        u8 __m2c_unaligned_byte3;
        u16 __m2c_unaligned_half4;
        u8 __m2c_unaligned_byte6;
        u8 __m2c_unaligned_byte7;
    }} __m2c_unaligned_row;
    int __m2c_unaligned_index;

    for (__m2c_unaligned_index = 0; __m2c_unaligned_index < {bound}; __m2c_unaligned_index++, __m2c_unaligned_src += 8, __m2c_unaligned_out++) {{
        __m2c_unaligned_row = *(struct __m2c_unaligned_input *)__m2c_unaligned_src;
        __m2c_unaligned_out->__m2c_unaligned_byte4 = (__m2c_unaligned_row.__m2c_unaligned_byte2 & {match['mask']}) >> {match['shift']};
        if (__m2c_unaligned_out->__m2c_unaligned_byte4 == 0) {{
            __m2c_unaligned_out->__m2c_unaligned_half0 = __m2c_unaligned_row.__m2c_unaligned_half4;
            __m2c_unaligned_out->__m2c_unaligned_byte2 = __m2c_unaligned_row.__m2c_unaligned_byte6;
            __m2c_unaligned_out->__m2c_unaligned_byte3 = __m2c_unaligned_row.__m2c_unaligned_byte7;
        }}
    }}
}}"""+source[ending+1:])
