from decomprepair.measured_stack_drafts import applies, rewrite


def copy_asm(load_base, store_base, words):
    lines = ['addiu $sp, $sp, -16']
    for prefix, base in [('l', load_base), ('s', store_base)]:
        for i in range(words):
            lines.extend((f'{prefix}wl $v{i}, {i*4}({base})', f'{prefix}wr $v{i}, {i*4+3}({base})'))
    return '\n'.join(lines)


PACKET = '''
extern s8 destination;
extern s32 ready;
void f(s8 page) {
    s8 sp0;
    s8 sp1;
    s8 sp2;
    s8 sp3;
    s32 counter;
    s8 *dst;
    dst = &destination;
    counter = 3;
    ready = 2;
    sp0 = 14;
    sp1 = 21;
    sp2 = 29;
    sp3 = page;
    do {
        *dst = 0;
        counter -= 1;
        dst += 1;
    } while (counter >= 0);
    M2C_FIELD(dst, s8 *, 0) = M2C_UNALIGNED32(sp0);
    M2C_FIELD(dst, M2C_UNK *, 4) = M2C_UNALIGNED32(sp4);
    M2C_FIELD(dst, M2C_UNK *, 8) = M2C_UNALIGNED32(sp8);
    M2C_FIELD(dst, s8 *, 0xC) = 0xF1;
}
'''


def test_outgoing_copy_preserves_a_single_record_transfer():
    asm = copy_asm('$sp', '$a2', 3)
    assert applies(asm)
    candidate = rewrite(PACKET, 'f', asm)
    assert 'byte' in candidate and 'ready = 2;' in candidate
    assert 'bytes[3] = page;' in candidate
    assert '*(__m2c_copy_packet_t *)__m2c_copy_dst = __m2c_copy_packet;' in candidate
    assert not rewrite(PACKET, 'f', asm.replace('11($a2)','10($a2)'))
    assert not rewrite(PACKET, 'f', asm, 'extern volatile s8 destination;')
    assert not rewrite(PACKET.replace('sp3 = page;', 'sp3 = page; use(sp0);'), 'f', asm)

    payload = PACKET.replace('s8 page)', 's8 page, u8 *payload)').replace(
        '    dst =', '    u8 sp4;\n    M2C_UNK spC;\n    u8 *read;\n    u8 *write;\n    read = payload;\n    dst =', 1
    ).replace('    counter = 3;', '    write = &sp4;').replace(
        '    sp3 = page;', '    sp3 = page;\n    do { *write = *read; write += 1; read += 1; } '
                         'while ((s32) write < (s32) &spC);\n    counter = 3;')
    assert '*__m2c_copy_src++' in rewrite(payload, 'f', asm)


def test_frame_index_requires_word_stores_and_an_indexed_reload():
    slots = list(range(0, 24, 4))
    pairs = ''.join(f'    s32 sp{x:X};\n' for x in slots)
    pairs += ''.join(f'    sp{x:X} = M2C_FIELD(&table, s32 *, {x});\n' for x in slots)
    source = 'extern M2C_UNK table;\ns32 f(s32 index) {\n'+pairs+'return *((index * 4) + sp);\n}'
    asm = 'addiu $sp, $sp, -24\n'
    for group in (slots[:3], slots[3:]):
        asm += ''.join(f'lw $t{i}, {x}($a2)\n' for i, x in enumerate(group))
        asm += ''.join(f'sw $t{i}, {x}($sp)\n' for i, x in enumerate(group))
    asm += '\nsll $a0, $a0, 2\naddu $a0, $a0, $sp\nlw $v0, 0($a0)'
    assert applies(asm)
    assert 'return __m2c_copy_table.words[index];' in rewrite(source, 'f', asm)
    assert not rewrite(source, 'f', asm.replace('16($sp)','12($sp)'))
    assert not rewrite(source, 'f', asm.replace('lw $v0, 0($a0)','lw $v0, 0($a1)'))
    assert not rewrite(source.replace('20);', '24);'), 'f', asm)


def test_incoming_record_uses_byte_views_and_stages_the_source_cursor():
    asm = copy_asm('$t0', '$sp', 2) + '''
lbu $v0, 2($sp)
lbu $v0, 4($sp)
lbu $v0, 5($sp)
lbu $v0, 6($sp)
addiu $t0, $t0, 8
addiu $sp, $sp, 16
'''
    source = '''
extern M2C_UNK replies;
extern u8 count;
void f(s8 *result, s16 *arg) {
    M2C_UNK sp0;
    u8 sp4;
    M2C_UNK *src;
    s16 *out;
    s32 i;
    s8 flags;
    u32 status;
    void *bytes;
    out = arg;
    flags = 0;
    src = &replies;
    i = 0;
    if ((s32) count > 0) {
        bytes = arg + 2;
        do {
            sp0 = M2C_UNALIGNED32(M2C_FIELD(src, M2C_UNK *, 0));
            sp4 = M2C_UNALIGNED32(M2C_FIELD(src, M2C_UNK *, 4));
            status = (u32) (sp2 & 0x30) >> 2;
            M2C_FIELD(bytes, s8 *, 1) = (s8) status;
            if (status == 0) {
                *out = sp4 | (sp5 << 8);
                flags |= 1 << i;
                M2C_FIELD(bytes, u8 *, 0) = sp6;
            }
            i += 1;
            src += 8;
            bytes += 4;
            out += 4;
        } while (i < (s32) count);
    }
    *result = flags;
}
'''
    candidate = rewrite(source, 'f', asm)
    assert 'reply.bytes[4] | (__m2c_copy_reply.bytes[5] << 8)' in candidate
    assert candidate.index('__m2c_copy_flags = 0') < candidate.index('__m2c_copy_cursor = replies')
    assert not rewrite(source, 'f', asm.replace('5($sp)','7($sp)'))
    assert not rewrite(source.replace('sp5 << 8','sp5 << 7'), 'f', asm)
