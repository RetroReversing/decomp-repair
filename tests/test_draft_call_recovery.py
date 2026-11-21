from decomprepair import draft_call_recovery as repairs


def annotated(source):
    return '\n'.join(f'/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                     for i, op in enumerate(source.splitlines()))


def test_only_rename_evidenced_external_direct_call_symbols():
    source = '''M2C_UNK .L80001000(int); /* extern */
M2C_UNK .L80002000(int); /* extern */
void f(int value) {
    /* Keep .L80001000(value) in documentation. */
    .L80001000(value);
    .L80002000(value);
}
'''
    asm = '''/* 00 80000000 0C000400 */ jal .L80001000
/* 04 80000004 00000000 */ nop
/* 08 80000008 0C000800 */ jal .L80002000
/* 0C 8000000C 00000000 */ nop
'''
    [(family, fixed)] = repairs.variants(source, 'f', asm, '', 'ido-7.1')
    assert family == 'initial_external_call_labels'
    assert 'M2C_UNK func_80001000(int);' in fixed
    assert '    func_80001000(value);' in fixed
    assert '    func_80002000(value);' in fixed
    assert '/* Keep .L80001000(value) in documentation. */' in fixed
    assert repairs.rename_local_calls(source, 'f', asm, 'int func_80001000(int);').count('.L80001000') == 3
    assert repairs.rename_local_calls(source, 'f', asm.replace('0C000400', '08000400')).count('.L80001000') == 3


def test_skip_calls_into_the_current_body_and_unverified_assembly():
    source = 'int .L80000004(void); /* extern */\nvoid f(void) { .L80000004(); }'
    asm = '''/* 00 80000000 0C000001 */ jal .L80000004
/* 04 80000004 00000000 */ nop
'''
    assert not repairs.rename_local_calls(source, 'f', asm)
    assert not repairs.rename_local_calls(source, 'f', 'jal .L80000004\nnop')
    outside = asm.replace('0C000001', '0C000800').replace('.L80000004', '.L80002000')
    assert not repairs.rename_local_calls(source.replace('.L80000004', '.L80002000'), 'f',
                                          outside + '.L80002000:\n')


def test_restore_the_memcpy_arguments_and_original_prototype_when_available():
    source = '''M2C_UNK memcpy(); /* extern */
s32 f(s32 dest, s32 size) {
    memcpy();
    return dest + size;
}
'''
    asm = annotated('''addiu $sp, $sp, -32
sw $s1, 20($sp)
move $s1, $a0
sw $s0, 16($sp)
sw $ra, 24($sp)
jal memcpy
move $s0, $a2
addu $v0, $s1, $s0
lw $ra, 24($sp)
lw $s1, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 32''')
    compiler = 'gcc-2.7.2-kmc'
    [(family, fixed)] = repairs.variants(source, 'f', asm, '', compiler)
    assert family == 'initial_forwarded_memcpy'
    assert 'f(s32 dest, void *arg1, s32 size)' in fixed
    assert 'memcpy((void *)dest, arg1, size);' in fixed
    assert 'void *memcpy(void *, const void *, unsigned int);' in fixed
    [(family, fixed)] = repairs.variants(source, 'f', asm, 'void *memcpy(void *d, const void *s, size_t n);', compiler)
    assert fixed.count('memcpy(') == 1
    assert not repairs.variants(source, 'f', asm, '#define memcpy tiny_copy', compiler)
    assert not repairs.variants(source, 'f', asm.replace('$s0, $a2', '$s0, $a1'), '', compiler)
    assert not repairs.variants(source, 'f', asm.replace('addu $v0', 'subu $v0'), '', compiler)
    assert not repairs.variants(source.replace('return dest + size', 'return size'), 'f', asm, '', compiler)
