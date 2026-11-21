"""Recover a record loop when m2c drops byte views of a MIPS unaligned copy."""

import re

from .integer_repair_support import IDENT, NUMBER, integer, view
from .mips import abi_register_names
from .pattern_repairs import close

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


_CHANNEL_ASM = re.compile(
    r'addiu \$sp, \$sp, -(?P<frame>0x10|16)\n'
    r'(?:addu \$a3, \$a1, \$zero|move \$a3, \$a1)\n'
    rf'lui \$a2, %hi\((?P<base>{IDENT}(?: \+ {NUMBER})?)\)\n'
    r'addiu \$a2, \$a2, %lo\((?P=base)\)\n'
    r'blez \$a0, (?P<read>\.L\w+)\n'
    r'(?:addu \$v1, \$zero, \$zero|move \$v1, \$zero)\n'
    r'(?P<loop>\.L\w+):\naddiu \$v1, \$v1, (?:0x1|1)\nslt \$v0, \$v1, \$a0\n'
    r'bnez \$v0, (?P=loop)\naddiu \$a2, \$a2, (?:0x1|1)\n(?P=read):\n'
    r'lwl \$v0, (?:0x0|0)?\(\$a2\)\nlwr \$v0, (?:0x3|3)\(\$a2\)\n'
    r'lb \$v1, (?:0x4|4)\(\$a2\)\nlb \$a0, (?:0x5|5)\(\$a2\)\n'
    r'swl \$v0, (?:0x0|0)?\(\$sp\)\nswr \$v0, (?:0x3|3)\(\$sp\)\n'
    r'sb \$v1, (?:0x4|4)\(\$sp\)\nsb \$a0, (?:0x5|5)\(\$sp\)\n'
    r'lbu \$v0, (?:0x1|1)\(\$sp\)\nandi \$v0, \$v0, (?:0x[cC]0|192)\nsrl \$v0, \$v0, (?:0x4|4)\n'
    r'bnez \$v0, (?P<exit>\.L\w+)\nsb \$v0, (?:0x3|3)\(\$a3\)\n'
    r'lbu \$v0, (?:0x4|4)\(\$sp\)\nlbu \$v1, (?:0x3|3)\(\$sp\)\nsll \$v0, \$v0, (?:0x8|8)\n'
    r'or \$v1, \$v1, \$v0\nsh \$v1, (?:0x0|0)?\(\$a3\)\n'
    r'lbu \$v0, (?:0x5|5)\(\$sp\)\nsb \$v0, (?:0x2|2)\(\$a3\)\n'
    r'(?P=exit):\njr \$ra\naddiu \$sp, \$sp, (?P=frame)'
)
_CHANNEL_BODY = re.compile(rf'''
    \s*(?:M2C_UNK|s32)\s+sp0\s*;\s*s8\s+sp4\s*;\s*s8\s+sp5\s*;
    (?P<locals>(?:\s*(?:s32\s+{IDENT}|u32\s+{IDENT}|(?:M2C_UNK|void)\s*\*\s*{IDENT})\s*;){{3}})
    \s*(?P<source>{IDENT})\s*=\s*(?:\(char\s*\*\)\s*)?&(?P<base>{IDENT})(?:\s*\+\s*(?P<offset>{NUMBER}))?\s*;
    \s*(?P<index>{IDENT})\s*=\s*0\s*;
    \s*if\s*\(\s*(?P<count>{IDENT})\s*>\s*0\s*\)\s*{{\s*do\s*{{
    \s*(?P=index)\s*\+=\s*1\s*;\s*(?P=source)\s*\+=\s*1\s*;
    \s*}}\s*while\s*\(\s*(?P=index)\s*<\s*(?P=count)\s*\)\s*;\s*}}
    \s*sp0\s*=\s*M2C_UNALIGNED32\(M2C_FIELD\((?P=source),\s*M2C_UNK\s*\*,\s*0\)\)\s*;
    \s*sp4\s*=\s*M2C_FIELD\((?P=source),\s*s8\s*\*,\s*4\)\s*;
    \s*sp5\s*=\s*M2C_FIELD\((?P=source),\s*s8\s*\*,\s*5\)\s*;
    \s*(?P<status>{IDENT})\s*=\s*\(u32\)\s*\(sp1\s*&\s*0x[cC]0\)\s*>>\s*4\s*;
    \s*M2C_FIELD\((?P<output>{IDENT}),\s*s8\s*\*,\s*3\)\s*=\s*\(s8\)\s*(?P=status)\s*;
    \s*if\s*\(\s*(?P=status)\s*==\s*0\s*\)\s*{{
    \s*M2C_FIELD\((?P=output),\s*s16\s*\*,\s*0\)\s*=\s*\(s16\)\s*\(sp3\s*\|\s*\(\(u8\)\s*sp4\s*<<\s*8\)\)\s*;
    \s*M2C_FIELD\((?P=output),\s*u8\s*\*,\s*2\)\s*=\s*\(u8\)\s*sp5\s*;\s*}}\s*
''', re.X)


def rewrite_channel(source, name, asm, context=''):
    """Keep the six-byte aggregate when the target reloads overlapping byte views."""
    row = '__repair_channel'
    if 'M2C_UNALIGNED32(' not in source or re.search(rf'\b{row}\b', source + context):
        return None
    lines = [' '.join(re.sub(r'/\*.*?\*/|#.*', '', line).split())
             for line in abi_register_names(asm or '').splitlines()]
    text = '\n'.join(line for line in lines if line and not line.startswith(('glabel ', 'endlabel ')))
    target = _CHANNEL_ASM.fullmatch(text)
    if not target or len({target['loop'], target['read'], target['exit']}) != 3:
        return None
    part = view(source, name)
    if not part or not (end := close(part.clean, part.opening, '{', '}')):
        return None
    match = _CHANNEL_BODY.fullmatch(part.clean[part.opening + 1:end - 1])
    if not match:
        return None
    pointer, index, status, count, output = (match[key] for key in ('source', 'index', 'status', 'count', 'output'))
    if len({pointer, index, status, count, output, match['base']}) != 6:
        return None
    signature = rf'\bvoid\s+{re.escape(name)}\s*\(\s*s32\s+{count}\s*,\s*void\s*\*\s*{output}\s*\)\s*$'
    if not re.search(signature, part.clean[:part.opening]):
        return None
    declared = re.findall(rf'(s32|u32|(?:M2C_UNK|void)\s*\*)\s*({IDENT})\s*;', match['locals'])
    types = {symbol: ''.join(kind.split()) for kind, symbol in declared}
    if types.get(pointer) not in ('M2C_UNK*', 'void*') or types.get(index) != 's32' or types.get(status) != 'u32':
        return None
    base, _, offset = target['base'].partition(' + ')
    if base != match['base'] or integer(offset or '0') != integer(match['offset'] or '0'):
        return None
    address = f'(u8 *)&{base}' + (f" + {match['offset']}" if match['offset'] else '')
    body = f"""
    struct {{ u8 bytes[6]; }} {row};
    u8 *{pointer};
    s32 {index};
    u32 {status};

    {pointer} = {address};
    for ({index} = 0; {index} < {count}; {index}++) {{
        {pointer}++;
    }}
    {row} = *(typeof({row}) *){pointer};
    {status} = (u32) ({row}.bytes[1] & 0xC0) >> 4;
    M2C_FIELD({output}, s8 *, 3) = (s8) {status};
    if ({status} == 0) {{
        M2C_FIELD({output}, s16 *, 0) = (s16) ({row}.bytes[3] | ((u8) {row}.bytes[4] << 8));
        M2C_FIELD({output}, u8 *, 2) = {row}.bytes[5];
    }}
"""
    return source[:part.opening + 1] + body + source[end - 1:]

def stack_copy(asm, views=(('lhu', 4), ('lbu', 6), ('lbu', 7))):
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
        if ({(op, slot+offset) for op, offset in views} <= reloads
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
    count = source.count('M2C_UNALIGNED32(')
    if count == 1:
        return rewrite_channel(source, name, asm, context)
    if count != 2 or not (copy := stack_copy(asm)):
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
