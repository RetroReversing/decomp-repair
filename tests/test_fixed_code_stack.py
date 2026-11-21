from decomprepair import measured_stack_drafts

DRAFT = '''
s32 rebuild_tables(void) {
    s32 sp25C;
    s32 sp260;
    s32 remaining;
    s32 index;
    s32 literal_result;
    s32 distance_result;
    s32 count;
    s32 *first;
    s32 *second;
    s32 *third;
    s32 *fourth;
    s32 *tail;
    void *left;
    void *right;
    if (M2C_FIELD(&table_state, s32 *, 16) == 0) {
        remaining = 0x8F;
        first = &sp25C;
        do { *first = 8; remaining -= 1; first -= 4; } while (remaining >= 0);
        index = 0x90;
        second = &sp260;
        do { *second = 9; index += 1; second += 4; } while (index < 0x100);
        if (index < 0x118) {
            third = &(&sp20[0])[index];
            do { *third = 7; index += 1; third += 4; } while (index < 0x118);
        }
        if (index < 0x120) {
            fourth = &(&sp20[0])[index];
            do { *fourth = 8; index += 1; fourth += 4; } while (index < 0x120);
        }
        left = (char *)&table_state + 24;
        M2C_FIELD(&table_state, s32 *, 24) = 7;
        literal_result = huft_build(&sp20[0], 0x120, 0x101, &lengths, &length_extra, left - 8, left);
        count = literal_result;
        if (count != 0) { M2C_FIELD(left, s32 *, -8) = 0; return literal_result; }
        tail = &sp20[0];
        do { *tail = 5; count += 1; tail += 4; } while (count < 0x1E);
        right = (char *)&table_state + 28;
        M2C_FIELD(&table_state, s32 *, 28) = 5;
        distance_result = huft_build(&sp20[0], 0x1E, 0, &distances, &distance_extra, right - 8, right);
        if (distance_result >= 2) {
            huft_free(M2C_FIELD(&table_state, s32 *, 16));
            M2C_FIELD(&table_state, s32 *, 16) = 0;
            return distance_result;
        }
        goto decode;
    }
decode:
    return inflate_codes(M2C_FIELD(&table_state, s32 *, 16), M2C_FIELD(&table_state, s32 *, 20),
        M2C_FIELD(&table_state, s32 *, 24), M2C_FIELD(&table_state, s32 *, 28)) != 0;
}
'''
ASM = '''
lw $v0, %lo(table_state + 16)($v0)
addiu $sp, $sp, -0x4B0
sw $s0, 1184($sp)
addiu $s0, $zero, 143
addiu $v0, $sp, 604
addiu $v0, $v0, -4
addiu $s0, $zero, 144
addiu $v1, $sp, 608
slti $v0, $s0, 256
addiu $v1, $v1, 4
slti $v0, $s0, 280
slti $v0, $s0, 288
addiu $a0, $sp, 32
addiu $a1, $zero, 288
addiu $a2, $zero, 257
addiu $a3, $a3, %lo(lengths)
addiu $s1, $s1, %lo(table_state + 24)
addiu $v0, $v0, %lo(length_extra)
jal huft_build
sw $s1, 24($sp)
addu $s0, $v0, $zero
slti $v0, $s0, 30
addiu $a0, $sp, 32
addiu $a1, $zero, 30
addiu $a3, $a3, %lo(distances)
addiu $v1, $v1, %lo(table_state + 28)
addiu $v0, $v0, %lo(distance_extra)
jal huft_build
sw $v1, 24($sp)
addu $s0, $v0, $zero
jal huft_free
lw $a1, %lo(table_state + 20)($a1)
jal inflate_codes
'''


def test_fixed_code_stack_reuses_one_array_and_the_builder_result():
    assert measured_stack_drafts.applies(ASM)
    fixed = measured_stack_drafts.rewrite(DRAFT, 'rebuild_tables', ASM)
    assert 's32 __m2c_copy_lengths[288];' in fixed
    assert '__m2c_copy_index = huft_build(__m2c_copy_lengths, 0x120' in fixed
    assert 'for (; __m2c_copy_index < 30;' in fixed
    assert 'sp20' not in fixed


def test_fixed_code_stack_rejects_changed_slot_or_unconfirmed_field():
    other_slot = ASM.replace('addiu $a0, $sp, 32', 'addiu $a0, $sp, 36', 1)
    assert not measured_stack_drafts.applies(other_slot)
    assert not measured_stack_drafts.rewrite(DRAFT, 'rebuild_tables', other_slot)
    assert not measured_stack_drafts.rewrite(DRAFT, 'rebuild_tables', ASM.replace('table_state + 20', 'other + 20'))
    assert not measured_stack_drafts.rewrite(DRAFT.replace('return literal_result;', 'return 1;'), 'rebuild_tables', ASM)
