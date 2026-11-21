from decomprepair.measured_kmc_byte_stride import variants


def test_masked_call_keeps_both_parameters():
    ops = '''
addiu $sp, $sp, -24
sw $s0, 16($sp)
move $s0, $a1
sw $ra, 20($sp)
jal lookup
andi $a1, $s0, 65535
sb $s0, 14($v0)
lw $ra, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''.strip().splitlines()
    rows = [(' ', x, x) for x in ops]
    rows[5] = ('r', ops[5], 'andi $a0, $a1, 65535')
    source = '''
void *lookup();
void f(s32 first, s8 second) {
    M2C_FIELD(lookup(second & 0xFFFF), s8 *, 14) = second;
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_masked_second_call_argument'
    assert 's32 second)' in fixed and 'lookup(first, second & 0xFFFF)' in fixed
    assert not variants(source, 'f', 'void f(s32, s8);', rows)


def test_byte_index_and_store_use_byte_stride():
    ops = '''
sll $s2, $v0, 2
lui $at, %hi(table)
addu $at, $at, $s2
sb $v0, %lo(table)($at)
'''.strip().splitlines()
    rows = [(' ', x, x) for x in ops] + [(' ', 'nop', 'nop')] * 10
    rows[0] = ('i', ops[0], 'sll $s2, $v0, 4')
    rows[3] = ('|', ops[3], 'sw $v0, %lo(table)($at)')
    source = '''
void f(void) {
    s32 off;
    void *base;
    base = off + &records;
    *(&table + off) = 2;
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_indexed_byte_global'
    assert 'base = off + (u8 *)&records;' in fixed
    assert '*(u8 *)((char *)&table + off) = 2;' in fixed
    assert not variants(source.replace('+ off) = 2', '+ other) = 2'), 'f', '', rows)


def test_indexed_pointer_and_byte_lookup_use_byte_addresses():
    ops = '''
sll $v1, $v1, 2
lui $at, %hi(pointers)
addu $at, $at, $v1
lw $v1, %lo(pointers)($at)
lui $at, %hi(bytes)
addu $at, $at, $v0
lbu $v0, %lo(bytes)($at)
'''.strip().splitlines()
    rows = [(' ', x, x) for x in ops] + [(' ', 'nop', 'nop')] * 10
    rows[0] = ('i', ops[0], 'sll $v1, $v1, 4')
    rows[6] = ('|', ops[6], 'lw $v0, %lo(bytes)($at)')
    source = '''
void f(s32 index) {
    void *entry;
    entry = *(&pointers + ((index & 0xFFFF) * 0x64));
    use(entry, *(&bytes + ((index & 0xFFFF) * 0x64)));
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_indexed_byte_global'
    assert '*(void **)((char *)&pointers' in fixed
    assert '*(u8 *)((char *)&bytes' in fixed
    assert not variants(source.replace('&bytes + ((index', '&bytes + ((other'), 'f', '', rows)
