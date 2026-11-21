from decomprepair import measured_word_drafts as repairs


def annotated(source):
    return '\n'.join(f'/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                     for i, op in enumerate(source.splitlines()))


def test_type_the_word_selected_by_the_byte_index():
    source = '''void *f(void *obj, u8 *input) {
    void *cursor;
    cursor = M2C_FIELD(obj, void **, 16);
    M2C_FIELD(obj, void **, 24) = (void *)(cursor + *((*input * 4) + M2C_FIELD(cursor, s32 *, 4)));
    return input + 1;
}
'''
    ops = '''lw $v1, 16($a0)
lbu $v0, 0($a1)
lw $a2, 4($v1)
sll $v0, $v0, 2
addu $v0, $v0, $a2
lw $v0, 0($v0)
addu $v1, $v1, $v0
addiu $v0, $a1, 1
jr $ra
sw $v1, 24($a0)'''
    [(family, fixed)] = repairs.variants(source, 'f', annotated(ops))
    assert family == 'initial_typed_index_word'
    assert '*(s32 *)((*input * 4) + M2C_FIELD(cursor, s32 *, 4))' in fixed
    assert not repairs.variants(source, 'f', annotated(ops.replace('lw $v0, 0', 'lh $v0, 0')))
    assert not repairs.variants(source.replace('s32 *, 4', 's32 *, 8'), 'f', annotated(ops))


def test_type_the_unsigned_comparison_and_stage_the_first_address():
    source = '''extern M2C_UNK table;
s32 f(u8 *left, u8 *right) {
    void *base;
    base = &table + 32;
    return (u32) *((*right * 4) + base) < (u32) *((*left * 4) + base);
}
'''
    ops = '''lbu $v1, 0($a0)
lui $a0, %hi(table + 0x20)
addiu $a0, $a0, %lo(table + 0x20)
lbu $v0, 0($a1)
sll $v1, $v1, 2
addu $v1, $v1, $a0
sll $v0, $v0, 2
addu $v0, $v0, $a0
lw $v1, 0($v1)
lw $v0, 0($v0)
jr $ra
sltu $v0, $v0, $v1'''
    asm = annotated(ops)
    [(family, fixed)] = repairs.variants(source, 'f', asm)
    assert family == 'initial_indexed_word_comparison'
    assert 'base = (char *)&table + 32;' in fixed
    assert '__repair_entry = base + (*left * 4);' in fixed
    assert '*(u32 *)(base + (*right * 4)) < (__repair_score = *(u32 *)__repair_entry)' in fixed
    assert repairs.variants(source.replace('&table', '(char *)&table'), 'f', asm) == [(family, fixed)]
    assert not repairs.variants(source, 'f', annotated(ops.replace('sltu', 'slt')))
    assert not repairs.variants(source.replace('&table + 32', '&table + 40'), 'f', asm)


def test_direct_mapped_store_uses_a_volatile_word_and_literal_segment():
    source = '''extern M2C_UNK D_A0000000;
s32 f(s32 offset, s32 value) {
    if (busy()) {
        return -1;
    }
    *(offset | (s32) &D_A0000000) = value;
    return 0;
}
'''
    ops = '''lui $v0, %hi(D_A0000000)
or $v0, $s0, $v0
sw $s1, %lo(D_A0000000)($v0)'''
    asm = annotated(ops)
    [(family, fixed)] = repairs.variants(source, 'f', asm)
    assert family == 'initial_mapped_word_store'
    assert '*(volatile u32 *)(offset | 0xA0000000U) = value;' in fixed
    assert not repairs.variants(source, 'f', annotated(ops.replace('sw $s1', 'sh $s1')))
    assert not repairs.variants(source, 'f', asm, 'extern int D_A0000000;')
