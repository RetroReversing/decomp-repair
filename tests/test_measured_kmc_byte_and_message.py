from decomprepair.measured_kmc_byte_and_message import variants


def test_unsigned_array_requires_target_and_extra_sign_extension():
    source = 'extern char bytes[];\nint f(int n) { return bytes[n]; }'
    rows = [(' ', 'lbu $v0, %lo(bytes)($at)', 'lbu $v0, %lo(bytes)($at)'),
            ('>', '', 'sll $v0, $v0, 0x18'), ('>', '', 'sra $v0, $v0, 0x18')]
    result = variants(source, 'f', '', rows)
    assert result[0][0] == 'measured_unsigned_byte_array'
    assert 'extern unsigned char bytes[];' in result[0][1]
    assert not variants(source, 'f', 'extern char bytes[];', rows)
    assert not variants(source, 'f', '', rows[:-1])
    assert not variants(source.replace('bytes[n]', '0'), 'f', '', rows)


def test_message_pointer_is_saved_before_flag_update():
    source = '''s32 f(void *arg) {
    s32 *slot;
    call(arg, &slot, 1);
    M2C_FIELD(arg, u16 *, 0xE) = (u16) (M2C_FIELD(arg, u16 *, 0xE) & 0xFFFE);
    if (slot == NULL) { goto empty; }
    return *slot;
empty: { return 0; }
}'''
    rows = [(' ', 'nop', 'nop')] * 17 + [
        ('o', '', 'andi $v0, $v0, 0xfffe'), ('o', '', 'sh $v0, 0xe($s0)'),
        ('r', 'lw $v1, 0x10($sp)', 'lw $v0, 0x10($sp)'),
        ('o', 'andi $v0, $v0, 0xfffe', ''), ('i', 'bnez $v1, 72', 'bnez $v0, 76'),
        ('o', 'sh $v0, 0xe($s0)', 'nop'), ('i', 'j f+76', 'j f+80'),
        ('r', 'lw $v0, ($v1)', 'lw $v0, ($v0)')]
    result = variants(source, 'f', '', rows)
    assert result[0][0] == 'measured_stack_message_schedule'
    fixed = result[0][1]
    assert fixed.index('__repair_message = slot;') < fixed.index('M2C_FIELD')
    assert 'if (__repair_message == NULL)' in fixed
    assert 'return *__repair_message;' in fixed
    assert not variants(source.replace('& 0xFFFE', '& 0xFFFF'), 'f', '', rows)
    assert not variants(source, 'f', '', rows[:-1])
