from decomprepair.measured_temporary_repairs import variants


def test_direct_return_keeps_null_fallback_and_access_width():
    source = '''
s32 f(void *p) {
    s32 result = 0;
    if (p) result = *(s32 *)((char *)p + 0x10);
    return result;
}
'''
    rows = [('r','lw $v0, 0x10($v1)','lw $v1, 0x10($v0)'),
            (' ','jr $ra','jr $ra'),('|','nop','move $v0, $v1')]
    expected = source.replace('result = *(s32','return *(s32').replace('return result;','return 0;')
    assert variants(source,'f',rows) == [('measured_direct_load_return',expected)]
    assert not variants(source.replace('0x10','0x14'),'f',rows)
    assert not variants(source.replace('return result;','done(); return result;'),'f',rows)
    assert not variants(source.replace('result = 0','result = 1'),'f',rows)
    assert not variants(source,'f',rows[:-1])


def test_scoped_alias_requires_register_trace_and_exclusively_field_uses():
    source = '''
void f(void *owner) {
    void *p;
    p = M2C_FIELD(owner, void **, 0xF4);
    if (p != NULL) {
        if (M2C_FIELD(p, u32 *, 0x5C)) use(M2C_FIELD(p, void **, 0x20));
    }
}
'''
    rows = [('r','lw $v0, 0xf4($s0)','lw $a0, 0xf4($s0)'),
            ('r','beqz $v0, done','beqz $a0, done'),('|','move $a0, $v0','nop'),
            (' ','lw $v0, 0x5c($a0)','lw $v0, 0x5c($a0)')]
    [(family,candidate)] = variants(source,'f',rows)
    assert family=='measured_null_guard_alias'
    assert 'void *__repair_subobject = p;' in candidate
    assert 'M2C_FIELD(__repair_subobject, u32 *, 0x5C)' in candidate
    assert 'M2C_FIELD(__repair_subobject, void **, 0x20)' in candidate
    assert 'if (p != NULL)' in candidate
    assert not variants(source.replace('0xF4','0xF8'),'f',rows)
    assert not variants(source.replace('if (M2C_FIELD(p','keep(p); if (M2C_FIELD(p'),'f',rows)
    assert not variants(source, 'f', rows[:-1])


def test_call_guard_stages_the_shift_in_the_result_byte():
    source = '''u32 status();
s32 f(void) {
    s32 result;
    result = 0;
    if (enabled) {
        result = (status() >> 3) & 1;
    }
    return result & 0xFF;
}
'''
    rows = [
        ('r', 'srl $v0, $v0, 3', 'srl $v1, $v0, 3'),
        ('r', 'andi $v1, $v0, 1', 'andi $v1, $v1, 1'),
    ]
    [(family, fixed)] = variants(source, 'f', rows)
    assert family == 'measured_staged_shift_mask'
    assert 'u8 result;' in fixed
    assert 'result = status();\n        result >>= 3;\n        result &= 1;' in fixed
    assert 'return result;' in fixed
    assert not variants(source.replace('>> 3', '>> 9'), 'f', rows)
    assert not variants(source, 'f', [rows[0], ('r', 'andi $v1, $a0, 1', rows[1][2])])


def test_word_shift_uses_the_mask_destination():
    source = '''s32 f(void) {
    u32 status;
    s32 result;
    status = read_status();
    result = (status >> 8) & 1;
    return result;
}
'''
    rows = [
        ('r', 'srl $a0, $v0, 8', 'srl $v1, $v0, 8'),
        (' ', 'andi $v0, $v0, 0x80', 'andi $v0, $v0, 0x80'),
        (' ', 'beqz $v0, .Lexit', 'beqz $v0, .Lexit'),
        ('r', 'andi $a0, $a0, 1', 'andi $a0, $v1, 1'),
    ]
    [(family, fixed)] = variants(source, 'f', rows)
    assert family == 'measured_staged_shift_mask'
    assert 'u32 result;' in fixed
    assert 'result = status >> 8;\n    result &= 1;' in fixed
    assert not variants(source.replace('return result;', 'return call(&result);'), 'f', rows)
