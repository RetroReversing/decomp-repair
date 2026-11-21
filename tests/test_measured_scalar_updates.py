from decomprepair import measured_scalar_updates as repairs


def annotate(asm):
    return '\n'.join(f'/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {line}'
                     for i, line in enumerate(asm.strip().splitlines()))


def test_ido_stages_the_global_byte_read_and_write():
    source = 'extern u8 clockByte;\nvoid f(void) { clockByte -= 8; }\n'
    target = '''
lui $v1, %hi(clockByte)
addiu $v1, $v1, %lo(clockByte)
lbu $v0, 0($v1)
addiu $v0, $v0, -8
jr $ra
sb $v0, 0($v1)
'''
    rows = [('r', 'target', 'draft')] * 5
    [(family, fixed)] = repairs.variants(source, 'f', '', 'ido-5.3', rows, annotate(target))
    assert family == 'staged_global_byte_decrement'
    assert '__repair_byte_value = clockByte;' in fixed
    assert 'clockByte = __repair_byte_value;' in fixed
    assert not repairs.variants(source.replace('-= 8', '-= 7'), 'f', '', 'ido-5.3', rows, annotate(target))
    assert not repairs.variants(source, 'f', '', 'ido-5.3', rows, annotate(target.replace('sb', 'sh')))


def test_stages_each_shift_in_the_packed_accumulator():
    source = '''s32 f(s32 a,s32 b,s32 c,s32 d) {
    return (d & 0xFF) + ((c & 0xFF) << 8) + ((b & 0xFF) << 16) + (a << 24);
}
'''
    rows = [('r', 'target', 'draft')] * 5
    [(family, fixed)] = repairs.variants(source, 'f', '', 'gcc-2.7.2-kmc', rows, annotate(repairs._PACK))
    assert family == 'staged_packed_bytes'
    assert '    __repair_pack_mid_high <<= 16;' in fixed
    assert '    __repair_pack_value += __repair_pack_high;' in fixed
    assert not repairs.variants(source.replace('<< 16', '<< 17'), 'f', '', 'gcc-2.7.2-kmc', rows,
                                annotate(repairs._PACK))


def test_only_decrement_a_dead_local_before_the_byte_store():
    source = '''extern void *state;
void f(void) {
    u8 count;
    count = read();
    M2C_FIELD(state, u8 *, 12) = (u8) (count - 1);
    M2C_FIELD(state, s8 *, 32) = 1;
    notify();
}
'''
    rows = [
        (' ', 'addiu $v0, $v0, -1', 'addiu $v0, $v0, -1'),
        (' ', 'sb $v0, 12($v1)', 'sb $v0, 12($v1)'),
        ('r', 'lui $v0, %hi(state)', 'lui $v1, %hi(state)'),
        ('r', 'lw $v0, %lo(state)($v0)', 'lw $v1, %lo(state)($v1)'),
        ('r', 'addiu $v1, $zero, 1', 'addiu $v0, $zero, 1'),
        (' ', 'jal notify', 'jal notify'),
        ('r', 'sb $v1, 32($v0)', 'sb $v0, 32($v1)'),
    ]
    [(family, fixed)] = repairs.variants(source, 'f', '', 'gcc-2.7.2-kmc', rows, '')
    assert family == 'decrement_local_before_byte_store'
    assert '12) = --count;' in fixed
    assert not repairs.variants(source.replace('notify();','notify(count);'), 'f', '', 'gcc-2.7.2-kmc', rows, '')
    assert not repairs.variants(source.replace('count = read()', 'count = read(&count)'), 'f', '',
                                'gcc-2.7.2-kmc', rows, '')
