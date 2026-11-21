"""Recover the typed inode page and byte map from a MIPS cache initializer."""

import re

from .integer_repair_support import IDENT

READ = '__osPfsRWInode'
_BODY = re.compile(
    rf'(?P<clear>{IDENT}) = 0xFF; (?P<dest>{IDENT}) = (?P<cache>{IDENT}) \+ 0xFF; '
    r'do { M2C_FIELD\((?P=dest), s8 \*, 0x101\) = 0; (?P=clear) -= 1; (?P=dest) -= 1; } '
    r'while \((?P=clear) >= 0\); M2C_FIELD\((?P=cache), s8 \*, 0x100\) = 0xFF; '
    rf'(?P<counter>{IDENT}) = 0; if \(M2C_FIELD\((?P<fs>{IDENT}), u8 \*, 0x64\) != 0\) {{ '
    rf'(?P<bank>{IDENT}) = 0 & 0xFF; (?P<loop>{IDENT}): (?P<first>{IDENT}) = 1; '
    r'if \((?P=bank) == 0\) { (?P=first) = M2C_FIELD\((?P=fs), s32 \*, 0x60\); } '
    rf'(?P<status>{IDENT}) = {READ}\((?P=fs), \(u16 \(\*\)\[\]\) &sp10\[0\], 0, (?P=bank)\); '
    rf'(?P<result>{IDENT}) = (?P=status); if \(!\(\((?P=status) != 0\) & \((?P=status) != 3\)\)\) {{ '
    rf'(?P<index>{IDENT}) = (?P=first); if \((?P=index) < 0x80\) {{ '
    rf'(?P<page>{IDENT}) = &\(&sp10\[0\]\)\[(?P=index)\]; do {{ (?P<entry>{IDENT}) = \*(?P=page); '
    rf'(?P<word>{IDENT}) = (?P=entry) & 0xFFFF; (?P=index) \+= 1; '
    rf'if \((?P=word) >= M2C_FIELD\((?P=fs), s32 \*, 0x60\)\) {{ (?P<high>{IDENT}) = \(u32\) (?P=word) >> 8; '
    rf'if \((?P=high) != (?P=bank)\) {{ (?P<slot>{IDENT}) = (?P=cache) \+ '
    r'\(\(\(u32\) \((?P=entry) & 0xFF\) >> 2\) \+ \(\((?P=high) & 7\) << 5\)\); '
    r'M2C_FIELD\((?P=slot), u8 \*, 0x101\) = \(u8\) \(M2C_FIELD\((?P=slot), u8 \*, 0x101\) \| \(1 << \((?P=bank) & 7\)\)\); '
    r'} } (?P=page) \+= 2; } while \((?P=index) < 0x80\); } '
    r'(?P=counter) \+= 1; (?P=bank) = (?P=counter) & 0xFF; '
    rf'if \(\(u32\) \((?P=counter) & 0xFF\) >= \(u8\) M2C_FIELD\((?P=fs), u8 \*, 0x64\)\) {{ goto (?P<done>{IDENT}); }} '
    r'goto (?P=loop); } } else { (?P=done): (?P=result) = 0; } return (?P=result);'
)


def evidence(rows):
    """Require the stack page, paired byte-map accesses and first-bank check."""
    calls = [line for line in rows if line.startswith(('jal ', 'jalr '))]
    required = {
        'addiu $sp, $sp, -304', 'sw $s0, 272($sp)', 'addiu $s5, $sp, 16',
        'addiu $a1, $sp, 16', 'andi $s0, $s3, 255', 'lw $s1, 96($s2)', 'lbu $v0, 100($s2)',
        'sb $zero, 257($v0)', 'sb $v0, 256($s4)',
        'lhu $a0, 0($a2)', 'sllv $t0, $s6, $v0', 'lbu $v1, 257($v0)', 'sb $v1, 257($v0)',
        'addiu $a2, $a2, 2', 'srl $v1, $v1, 8', 'srl $v0, $v0, 2', 'sll $v1, $v1, 5',
    }
    return calls == [f'jal {READ}'] and required.issubset(rows) and rows.count('slti $v0, $a1, 128') == 2


def rewrite(part, name, context, loc, body, end, rows):
    match = _BODY.fullmatch(body)
    if (not match or not evidence(rows) or re.search(rf'\b{READ}\b', context)
            or re.search(r'^\s*#\s*define\s+(bank|page|map|unused)\b', part.clean + context, re.M)):
        return None
    fs, cache = match['fs'], match['cache']
    types = {match[key]: 's32' for key in ('clear', 'counter', 'bank', 'first', 'status', 'result', 'index', 'word')}
    types.update({match['dest']: 'void*', match['page']: 'u16*', match['entry']: 'u16',
                  match['high']: 'u32', match['slot']: 'void*'})
    if len(types) != 13 or set(types) & {fs, cache} or fs == cache or loc != types:
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(void \*{fs}, void \*{cache}\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    decl = re.search(rf'\bs32 {READ}\(void \*, u16 \(\*\)\[\], M2C_UNK, s32\);', part.clean[:signature.start()])
    if not decl or len(re.findall(rf'\b{READ}\b', part.clean)) != 2:
        return None
    return part.source[:decl.start()] + f'''typedef struct {{
    unsigned short unused[128];
    unsigned char bank;
    unsigned char map[256];
}} __m2c_copy_cache_t;
typedef union {{
    unsigned short word;
    struct {{ unsigned char bank, page; }} bytes;
}} __m2c_copy_entry_t;
int {READ}(void *, __m2c_copy_entry_t *, unsigned char, unsigned char);
''' + part.source[decl.end():signature.start()] + f'''int {name}(void *{fs}, __m2c_copy_cache_t *{cache}) {{
    __m2c_copy_entry_t __m2c_copy_page[128];
    unsigned char __m2c_copy_bank;
    __m2c_copy_entry_t __m2c_copy_entry;
    int __m2c_copy_index;
    int __m2c_copy_offset;
    int __m2c_copy_slot;
    int __m2c_copy_status;
    for (__m2c_copy_index = 0; __m2c_copy_index < 256; __m2c_copy_index++) {{
        {cache}->map[__m2c_copy_index] = 0;
    }}
    {cache}->bank = 255;
    for (__m2c_copy_bank = 0; __m2c_copy_bank < *((unsigned char *){fs} + 100); __m2c_copy_bank++) {{
        __m2c_copy_offset = __m2c_copy_bank > 0 ? 1 : *(int *)((unsigned char *){fs} + 96);
        __m2c_copy_status = {READ}({fs}, __m2c_copy_page, 0, __m2c_copy_bank);
        if (__m2c_copy_status != 0 && __m2c_copy_status != 3) return __m2c_copy_status;
        for (__m2c_copy_index = __m2c_copy_offset; __m2c_copy_index < 128; __m2c_copy_index++) {{
            __m2c_copy_entry = __m2c_copy_page[__m2c_copy_index];
            if (__m2c_copy_entry.word >= *(int *)((unsigned char *){fs} + 96)
                    && __m2c_copy_entry.bytes.bank != __m2c_copy_bank) {{
                __m2c_copy_slot = (__m2c_copy_entry.bytes.page >> 2) + ((__m2c_copy_entry.bytes.bank % 8) * 32);
                {cache}->map[__m2c_copy_slot] |= 1 << (__m2c_copy_bank % 8);
            }}
        }}
    }}
    return 0;
}}''' + part.source[end+1:]
