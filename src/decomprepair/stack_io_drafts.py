"""Recover stack aggregates passed to IO routines in two measured MIPS drafts."""

import re

from .integer_repair_support import IDENT, NUMBER, integer

_REQUEST_COPY = (
    'lwl $v0, 0($sp)', 'lwr $v0, 3($sp)', 'lwl $v1, 4($sp)', 'lwr $v1, 7($sp)',
    'swl $v0, 0($a3)', 'swr $v0, 3($a3)', 'swl $v1, 4($a3)', 'swr $v1, 7($a3)',
)
_REQUEST = re.compile(
    rf'(?P<dest>{IDENT}) = (?:\(char \*\))?&(?P<base>{IDENT}) \+ (?P<offset>{NUMBER}); '
    rf'(?P<index>{IDENT}) = 0; M2C_FIELD\(&(?P=base), s32 \*, (?P<status>{NUMBER})\) = 1; '
    rf'sp1 = (?P<b1>{NUMBER}); M2C_FIELD\(&(?P=base), s8 \*, (?P<command>{NUMBER})\) = (?P<arg>{IDENT}); '
    rf'sp0 = (?P<b0>{NUMBER}); sp2 = (?P<b2>{NUMBER}); sp3 = (?P=arg); '
    + ' '.join(rf'sp{i} = (?P<b{i}>{NUMBER});' for i in range(4, 8)) + ' '
    rf'if \(\(s32\) M2C_FIELD\(&(?P<count>{IDENT}), u8 \*, (?P<count_offset>{NUMBER})\) > 0\) {{ do {{ '
    r'M2C_FIELD\((?P=dest), s8 \*, 0\) = M2C_UNALIGNED32\(sp0\); '
    r'M2C_FIELD\((?P=dest), M2C_UNK \*, 4\) = M2C_UNALIGNED32\(sp4\); '
    r'(?P=index) \+= 1; (?P=dest) \+= 8; } '
    r'while \((?P=index) < \(s32\) M2C_FIELD\(&(?P=count), u8 \*, (?P=count_offset)\)\); } '
    rf'\*(?P=dest) = (?P<end>{NUMBER});'
)
INODE_READ = '__osPfsRWInode'
_INODE_BODY = re.compile(
    rf'(?P<total>{IDENT}) = 0; if \(!\(M2C_FIELD\((?P<arg>{IDENT}), s32 \*, 0\) & 1\)\) {{ return 5; }} '
    rf'(?P<status>{IDENT}) = 2; if \(__osCheckId\((?P=arg)\) != 2\) {{ '
    rf'(?P<bank>{IDENT}) = 0; if \(\(u8\) M2C_FIELD\((?P=arg), u8 \*, 0x64\) > 0U\) {{ '
    rf'(?P<loop>{IDENT}): (?P<wanted>{IDENT}) = (?P=bank) & 0xFF; '
    rf'(?P=status) = {INODE_READ}\((?P=arg), \(u16 \(\*\)\[\]\) &sp10\[0\], 0, (?P=wanted)\); '
    rf'if \((?P=status) == 0\) {{ (?P<first>{IDENT}) = 1; '
    r'if \((?P=wanted) == 0\) { (?P=first) = M2C_FIELD\((?P=arg), s32 \*, 0x60\); } '
    rf'(?P<index>{IDENT}) = (?P=first); if \((?P=index) < 0x80\) {{ '
    rf'(?P<cursor>{IDENT}) = &\(&sp10\[0\]\)\[(?P=index)\]; '
    r'do { (?P=index) \+= 1; (?P=total) \+= \*(?P=cursor) == 3; (?P=cursor) \+= 2; } '
    r'while \((?P=index) < 0x80\); } (?P=bank) \+= 1; '
    rf'if \(\(u32\) \((?P=bank) & 0xFF\) >= \(u8\) M2C_FIELD\((?P=arg), u8 \*, 0x64\)\) {{ goto (?P<done>{IDENT}); }} '
    rf'goto (?P=loop); }} }} else {{ (?P=done): \*(?P<result>{IDENT}) = (?P=total) << 8; (?P=status) = 0; }} }} '
    r'return (?P=status);'
)


def _rows(lines):
    # Canonicalize numeric operands while preserving relocations and labels.
    return tuple(re.sub(r'(?<![\w])(-?0x[\da-fA-F]+)\b', lambda m: str(int(m[1], 16)),
                        ' '.join(line.split())) for line in lines)


def request_evidence(lines):
    rows = _rows(lines)
    text = '\n'.join(rows)
    return ('\n'.join(_REQUEST_COPY) in text and 'addiu $sp, $sp, -16' in rows
            and 'addiu $a3, $a3, 8' in rows and 'slt $v0, $a2, $v0' in rows
            and 'addiu $a2, $a2, 1' in rows and sum(line.startswith('lbu ') for line in rows) == 2
            and not any(line.startswith(('jal ', 'jalr ')) for line in rows))


def request(part, name, context, loc, body, end, lines, resolve):
    match = _REQUEST.fullmatch(body)
    if not match or not resolve or not request_evidence(lines):
        return None
    if loc != ({f'sp{i}': 's8' for i in range(8)} | {match['dest']: 's8*', match['index']: 's32'}):
        return None
    arg, base, count = (match[key] for key in ('arg', 'base', 'count'))
    if len({arg, base, count, match['dest'], match['index']}) != 5:
        return None
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\(s8 {arg}\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    prefix = part.source[:signature.start()]
    for symbol in (base, count):
        decl = re.search(rf'\bextern M2C_UNK {symbol};', prefix)
        if not decl or re.search(rf'\bvolatile\b[^;{{}}\n]*\b{symbol}\b', context):
            return None
        prefix = prefix[:decl.start()] + prefix[decl.end():]

    rows = _rows(lines)
    names = {}
    for field, (symbol, op, reg, ctype) in {
        'offset': (base, 'addiu', '$a3, $a3', 'unsigned char'),
        'status': (base, 'sw', '$v0', 'int'),
        'command': (base, 'sb', '$a0', 'unsigned char'),
        'count_offset': (count, 'lbu', None, 'unsigned char'),
    }.items():
        offset = integer(match[field])
        address = resolve(symbol)
        if address is None or not 0 <= address + offset <= 0xffffffff:
            return None
        reloc = f'%lo({symbol} + {offset})'
        if field == 'count_offset':
            hits = {line for line in rows if line.startswith('lbu ')}
            if hits != {f'lbu {register}, {reloc}({register})' for register in ('$a1', '$v0')}:
                return None
        elif f'{op} {reg}, {reloc}' + ('' if field == 'offset' else '($at)') not in rows:
            return None
        alias = f'D_{address + offset:08X}'
        if alias in names.values() or re.search(rf'\b{alias}\b', part.clean + context):
            return None
        names[field] = alias
        prefix += f'extern {ctype} {alias};\n'

    # Track byte stores through constant registers, including the branch delay slot.
    values = {'$a0': arg}
    stores = {}
    for line in rows:
        if line in _REQUEST_COPY:
            break
        if hit := re.fullmatch(r'addiu (\$\w+), \$zero, (\d+)', line):
            values[hit[1]] = int(hit[2])
        if hit := re.fullmatch(r'sb (\$\w+), ([0-7])\(\$sp\)', line):
            offset = int(hit[2])
            if offset in stores:
                return None
            stores[offset] = values.get(hit[1])
    expected = {i: arg if i == 3 else integer(match[f'b{i}']) for i in range(8)}
    stop = integer(match['end'])
    if (stores != expected or any(isinstance(n, int) and not 0 <= n <= 255 for n in expected.values())
            or '\n'.join((f'addiu $v0, $zero, {stop}', 'sb $v0, 0($a3)')) not in '\n'.join(rows)):
        return None
    initial = ''.join(f'    __m2c_copy_packet.bytes[{i}] = {value};\n' for i, value in expected.items())
    return prefix.lstrip() + f'''typedef struct {{ unsigned char bytes[8]; }} __m2c_copy_packet_t;
void {name}(unsigned char {arg}) {{
    unsigned char *__m2c_copy_cursor = &{names['offset']};
    __m2c_copy_packet_t __m2c_copy_packet;
    int __m2c_copy_index;
    {names['command']} = {arg};
    {names['status']} = 1;
{initial}    for (__m2c_copy_index = 0; __m2c_copy_index < {names['count_offset']}; __m2c_copy_index++) {{
        *(__m2c_copy_packet_t *)__m2c_copy_cursor = __m2c_copy_packet;
        __m2c_copy_cursor += sizeof(__m2c_copy_packet_t);
    }}
    *__m2c_copy_cursor = {stop};
}}''' + part.source[end+1:]


def inode_evidence(lines):
    rows = _rows(lines)
    calls = [line for line in rows if line.startswith(('jal ', 'jalr '))]
    required = {
        'addiu $sp, $sp, -304', 'sw $s0, 272($sp)', 'addiu $s4, $sp, 16',
        'addiu $a1, $sp, 16', 'addu $a2, $zero, $zero', 'andi $s0, $s1, 255',
        'lw $v0, 0($s2)', 'lbu $v0, 100($s2)', 'lw $v0, 96($s2)',
        'lhu $v0, 0($v1)', 'xori $v0, $v0, 3', 'addiu $v1, $v1, 2',
        'sll $v0, $s3, 8', 'sw $v0, 0($s5)',
    }
    return (calls == ['jal __osCheckId', f'jal {INODE_READ}']
            and required.issubset(rows) and rows.count('slti $v0, $a0, 128') == 2)


def inode(part, name, context, loc, body, end, lines):
    match = _INODE_BODY.fullmatch(body)
    if not match or not inode_evidence(lines):
        return None
    integers = [match[key] for key in ('total', 'status', 'bank', 'wanted', 'first', 'index')]
    arg, result = match['arg'], match['result']
    if len(set(integers + [arg, result, match['cursor']])) != 9:
        return None
    if loc != (dict.fromkeys(integers, 's32') | {match['cursor']: 'u16*'}):
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(void \*{arg}, s32 \*{result}\)\s*$', part.clean[:part.opening])
    if not signature or re.search(rf'\b{INODE_READ}\b', context):
        return None
    decl = re.search(rf'\bs32 {INODE_READ}\(void \*, u16 \(\*\)\[\], M2C_UNK, s32\);', part.clean[:signature.start()])
    if not decl or len(re.findall(rf'\b{INODE_READ}\b', part.clean)) != 2:
        return None
    return (part.source[:decl.start()] + decl[0].replace('u16 (*)[]', 'u16 *')
            + part.source[decl.end():part.opening+1] + f'''
    u16 __m2c_copy_words[128];
    u32 __m2c_copy_bank;
    s32 __m2c_copy_index;
    s32 __m2c_copy_first;
    u32 __m2c_copy_wanted;
    u32 __m2c_copy_free = 0;
    s32 __m2c_copy_status;
    if (!(M2C_FIELD({arg}, u32 *, 0) & 1)) return 5;
    if (__osCheckId({arg}) == 2) return 2;
    __m2c_copy_bank = 0;
    if (__m2c_copy_free < M2C_FIELD({arg}, u8 *, 0x64)) {{
        do {{
            __m2c_copy_wanted = __m2c_copy_bank & 0xff;
            __m2c_copy_status = __osPfsRWInode({arg}, __m2c_copy_words, 0, __m2c_copy_wanted);
            if (__m2c_copy_status != 0) return __m2c_copy_status;
            __m2c_copy_first = __m2c_copy_wanted ? 1 : M2C_FIELD({arg}, s32 *, 0x60);
            for (__m2c_copy_index = __m2c_copy_first; __m2c_copy_index < 128; __m2c_copy_index++) {{
                __m2c_copy_free += __m2c_copy_words[__m2c_copy_index] == 3;
            }}
            __m2c_copy_bank++;
        }} while ((__m2c_copy_bank & 0xff) < M2C_FIELD({arg}, u8 *, 0x64));
    }}
    *{result} = __m2c_copy_free << 8;
    return 0;
}}''' + part.source[end+1:])
