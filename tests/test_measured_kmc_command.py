from decomprepair.measured_kmc_command import variants


def test_stages_command_and_removes_stale_allocator_argument():
    ops = '''
jal allocate
move $s1, $v0
move $s2, $v0
jal init
move $a0, $s2
lw $v1, 20($s1)
lui $a0, 55864
ori $a0, $a0, 3
addiu $v0, $v1, 8
sw $v0, 20($s1)
sw $a0, ($v1)
jal allocate
sw $s2, 4($v1)
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops] + [(' ', 'nop', 'nop')] * 30
    rows[10] = ('r', ops[10], 'sw $a1, ($v1)')
    rows += [('>', '', 'lui $a1, 55864'), ('>', '', 'ori $a1, $a1, 3')]
    source = '''
s32 allocate();
void f(void) {
    s32 value;
    void *context;
    void *cursor;
    context = get();
    value = allocate();
    init(value);
    cursor = M2C_FIELD(context, void **, 20);
    M2C_FIELD(context, void **, 20) = (void *) (cursor + 8);
    M2C_FIELD(cursor, s32 *, 0) = 0xDA380003;
    M2C_FIELD(cursor, s32 *, 4) = value;
    value = allocate(0xDA380003);
    use(value);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_staged_command_word'
    assert 'u32 value;' in fixed
    assert '__repair_command_word = 0xDA380003;' in fixed
    assert fixed.count('allocate();') == 3
    assert not variants(source.replace('allocate();', 'allocate(void);', 1), 'f', '', rows)
    assert not variants(source.replace('0xDA380003;', '0xDA380004;', 1), 'f', '', rows)
