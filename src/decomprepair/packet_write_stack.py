"""Recover the separate status object and unaligned reply in a packet write."""

import re

from .integer_repair_support import IDENT, NUMBER, integer
from .mips import normalized_integer_lines

STATUS = 'pakQueryStatus'
_CALLS = ('pif_lock', STATUS, STATUS, 'pfs_build_write_cmd', '__osSiRawStartDma',
          'osRecvMesg', '__osSiRawStartDma', 'osRecvMesg', 'pif_unlock')
_BODY = re.compile(
    rf'pif_lock\(\); (?P<base>{IDENT}) = (?:\(char \*\))?&(?P<order>{IDENT}) \+ (?P<offset>{NUMBER}); '
    rf'(?P<result>{IDENT}) = {STATUS}\((?P<queue>{IDENT}), &sp20\); if \((?P=result) == 0\) {{ '
    rf'(?P<kind>{IDENT}) = sp20 & 0xC000 & 0xFFFF; '
    rf'if \((?P=kind) == 0x8000\) {{ if \(\(u32\) \((?P<channel>{IDENT}) & 0xFF\) >= 0x40U\) {{ '
    r'(?P=result) = -1U; } } else if \((?P=kind) != 0xC000\) { (?P=result) = 8; } '
    rf'if \((?P=result) != 0\) {{ }} else {{ (?P<loop>{IDENT}): if \(sp22 & 0x80\) {{ '
    rf'{STATUS}\((?P=queue), &sp20\); goto (?P=loop); }} pfs_build_write_cmd\((?P=channel) & 0xFF, (?P<data>{IDENT})\); '
    rf'(?P<dma>{IDENT}) = (?:\(char \*\))?&(?P=order) \+ (?P=offset); '
    r'__osSiRawStartDma\(1, (?P=dma)\); osRecvMesg\((?P=queue), 0, 1\); __osSiRawStartDma\(0, (?P=dma)\); '
    rf'M2C_FIELD\(&(?P<stream>{IDENT}), s8 \*, (?P<stamp>{NUMBER})\) = 5; osRecvMesg\((?P=queue), 0, 1\); '
    + ' '.join(rf'sp{slot} = M2C_UNALIGNED32\(M2C_FIELD\((?P=base), M2C_UNK \*, {offset}\)\);'
               for slot, offset in (('10', '4'), ('14', '8'), ('18', '0xC'))) + ' '
    r'(?P=result) = \(u32\) \(sp11 & 0xC0\) >> 4; } } pif_unlock\(\); return (?P=result);'
)
_DECLARATIONS = {
    'M2C_UNK __osSiRawStartDma(M2C_UNK, void *);',
    'M2C_UNK osRecvMesg(s32, M2C_UNK, M2C_UNK);',
    'u32 pakQueryStatus(s32, u16 *);',
    'M2C_UNK pfs_build_write_cmd(s32, M2C_UNK);',
    'M2C_UNK pif_lock();',
    'M2C_UNK pif_unlock();',
}


def _instructions(lines):
    text = '\n'.join(' '.join(line.split()) for line in lines)
    text = re.sub(r'\((0x[\da-fA-F]+) & 0xFFFF\)', r'\1', text)
    return normalized_integer_lines(text.splitlines())


def evidence(rows):
    calls = tuple(line[4:] for line in rows if line.startswith(('jal ', 'jalr ')))
    if calls != _CALLS or rows.count('addiu $a1, $sp, 32') != 2:
        return False
    inbound = tuple(
        f'{op} {reg}, {offset + delta}($s2)'
        for reg, offset in (('$v0', 4), ('$v1', 8), ('$a0', 12))
        for op, delta in (('lwl', 0), ('lwr', 3))
    )
    local = tuple(
        f'{op} {reg}, {offset + delta}($sp)'
        for reg, offset in (('$v0', 16), ('$v1', 20), ('$a0', 24))
        for op, delta in (('swl', 0), ('swr', 3))
    )
    read = ('lbu $v0, 17($sp)', 'andi $v0, $v0, 192', 'srl $s0, $v0, 4')
    return ('\n'.join(inbound + local + read) in '\n'.join(rows) and 'addiu $sp, $sp, -64' in rows
            and {'lhu $v1, 32($sp)', 'lbu $v0, 34($sp)', 'andi $v0, $v0, 128',
                 'andi $v1, $v1, 49152', 'sltiu $v0, $v0, 64'}.issubset(rows))


def applies(lines):
    return evidence(_instructions(lines))


def rewrite(part, name, context, loc, body, end, lines):
    match = _BODY.fullmatch(body)
    if not match or not evidence(rows := _instructions(lines)):
        return None
    queue, channel, data, order, stream = (match[key] for key in ('queue', 'channel', 'data', 'order', 'stream'))
    types = {'sp10': 'M2C_UNK', 'sp14': 'M2C_UNK', 'sp18': 'M2C_UNK', 'sp20': 'u16',
             match['kind']: 's32', match['result']: 'u32', match['base']: 'void*', match['dma']: 'void*'}
    if len(types) != 8 or types != loc or len({queue, channel, data, order, stream}) != 5:
        return None
    signature = re.search(rf'\bu32\s+{re.escape(name)}\(s32 {queue}, s32 {channel}, M2C_UNK {data}\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return None
    prefix = ' '.join(part.clean[:signature.start()].split())
    declarations = re.findall(r'[^;]+;', prefix)
    expected = _DECLARATIONS | {f'extern M2C_UNK {order};', f'extern M2C_UNK {stream};'}
    existing = '|'.join(map(re.escape, {*_CALLS, order, stream, name}))
    if (len(declarations) != len(expected) or {decl.strip() for decl in declarations} != expected
            or not prefix.endswith(';') or re.search(rf'\b(?:{existing})\b', context)
            or part.clean[end+1:].strip()
            or re.search(r'^\s*#\s*define\s+bytes\b', context, re.M)):
        return None
    offset, stamp = match['offset'], match['stamp']
    if not {f'addiu $s2, $s2, %lo({order} + {integer(offset)})',
            f'addiu $s0, $s0, %lo({order} + {integer(offset)})',
            f'sb $v0, %lo({stream} + {integer(stamp)})($at)'}.issubset(rows):
        return None
    return f'''int __osSiRawStartDma(int, void *);
int osRecvMesg(int, void *, int);
int {STATUS}(int, unsigned char *);
void pfs_build_write_cmd(unsigned char, unsigned char *);
void pif_lock(void);
void pif_unlock(void);
extern unsigned char {stream}[];
extern unsigned char {order}[];
typedef struct {{ unsigned char bytes[12]; }} __m2c_copy_reply_t;

int {name}(int {queue}, unsigned char {channel}, unsigned char *{data}) {{
    int __m2c_copy_result;
    unsigned short __m2c_copy_kind;
    unsigned char *__m2c_copy_base = {order} + {offset};
    __m2c_copy_reply_t __m2c_copy_reply;
    unsigned char __m2c_copy_status[4];
    pif_lock();
    __m2c_copy_result = {STATUS}({queue}, __m2c_copy_status);
    __m2c_copy_kind = *(unsigned short *)__m2c_copy_status & 0xc000;
    if (__m2c_copy_result == 0) {{
        switch (__m2c_copy_kind) {{
        case 0x8000:
            if ({channel} >= 0x40) __m2c_copy_result = -1;
            break;
        case 0xc000:
            break;
        default:
            __m2c_copy_result = 8;
        }}
    }}
    if (__m2c_copy_result != 0) {{
        pif_unlock();
        return __m2c_copy_result;
    }}
    while (__m2c_copy_status[2] & 0x80) {STATUS}({queue}, __m2c_copy_status);
    pfs_build_write_cmd({channel}, {data});
    __osSiRawStartDma(1, {order} + {offset});
    osRecvMesg({queue}, 0, 1);
    __osSiRawStartDma(0, {order} + {offset});
    {stream}[{stamp}] = 5;
    osRecvMesg({queue}, 0, 1);
    __m2c_copy_base += 4;
    __m2c_copy_reply = *(__m2c_copy_reply_t *)__m2c_copy_base;
    __m2c_copy_result = (__m2c_copy_reply.bytes[1] & 0xc0) >> 4;
    pif_unlock();
    return __m2c_copy_result;
}}\n'''
