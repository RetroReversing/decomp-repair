from decomprepair.measured_immediate_repairs import variants


def same(text):
    return (' ',text,text)


def test_call_register_binds_exact_argument_even_with_other_uses_of_literal():
    source = 'int f(void) { check(3); return base + pick(3, read(3, 3)); }'
    diff = [('i','addiu $a0, $zero, 7','addiu $a0, $zero, 3'),
            same('jal pick'),same('nop')]
    assert variants(source,'f',diff) == [
        ('measured_call_literal',source.replace('pick(3,','pick(7,')),
    ]
    assert not variants(source.replace('check(3)','pick(3)'), 'f',diff)
    assert not variants(source,'f',diff[:1]+[same('move $a0, $v1')]+diff[1:])
    assert not variants(source,'f',diff[:1]+[same('bnez $t0, other')]+diff[1:])


def test_two_immediates_in_one_call_are_tried_together():
    source = 'int f(void) { return create(1, 12U); }'
    diff = [('i','addiu $a0, $zero, 332','addiu $a0, $zero, 1'),
            ('i','addiu $a1, $zero, 14','addiu $a1, $zero, 12'), same('sw $ra, 20($sp)'),
            same('jal create'),same('nop')]
    assert variants(source,'f',diff) == [('measured_call_literal','int f(void) { return create(332, 14U); }')]
    assert not variants(source,'f',diff+[('r','move $a1, $v0','move $a2, $v0')])


def test_branch_mask_requires_a_matching_branch_and_unique_source_site():
    source = 'int f(int x) { if (!(x & 0x10)) return 0; return x; }'
    rows = [('i','andi $v0, $v1, 4','andi $v0, $v1, 0x10'), same('bnez $v0, next')]
    assert variants(source,'f',rows) == [('measured_branch_mask',source.replace('0x10','0x4'))]
    assert not variants(source,'f',rows[:1])
    assert not variants(source,'f',[rows[0],same('bnez $a0, next')])
    assert not variants(source.replace('return x;', 'return (x & 0x10);'),'f',rows)


def test_byte_offsets_use_the_same_access_width_direction_and_base():
    source = 'void f(char *p) { M2C_FIELD(p, s8 *, 1) = 0; }'
    rows = [('i','sb $zero, ($v0)','sb $zero, 1($v0)')]
    assert variants(source,'f',rows) == [('measured_byte_offset',source.replace(', 1)',', 0)'))]
    assert not variants(source,'f',[('i','sb $zero, ($v1)','sb $zero, 1($v0)')])
    assert not variants(source,'f',[('i','sb $zero, -0x4($v0)','sb $zero, 1($v0)')])
    source = 'int f(void *p) { return *(s32 *)((char *)p + 0x10); }'
    rows = [('i','lw $v0, 0x18($v1)','lw $v0, 0x10($v1)')]
    assert variants(source,'f',rows) == [('measured_byte_offset',source.replace('0x10','0x18'))]
    assert not variants(source,'f',[('i','lw $v0, 0x18($sp)','lw $v0, 0x10($sp)')])
