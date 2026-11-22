from decomprepair import table_cursor_index as r

ASM = '''glabel f
/* 0 80073A00 00002021 */  addu       $a0, $zero, $zero
/* 4 80073A04 3C03800E */  lui        $v1, %hi(D_A)
/* 8 80073A08 24631A70 */  addiu      $v1, $v1, %lo(D_A)
/* C 80073A0C AC600000 */  sw         $zero, 0x0($v1)
/* 10 80073A10 24840001 */  addiu      $a0, $a0, 0x1
/* 14 80073A14 2C820004 */  sltiu      $v0, $a0, 0x4
/* 18 80073A18 1440FFFC */  bnez       $v0, .L80073A0C
/* 1C 80073A1C 24630004 */  addiu      $v1, $v1, 0x4
/* 20 80073A20 03E00008 */  jr         $ra
/* 24 80073A24 00000000 */  nop
'''

DRAFT = '''extern s32 D_A;

void f(void) {
    s32 *var_v1;
    u32 var_a0;

    var_a0 = 0;
    var_v1 = &D_A;
    do {
        *var_v1 = 0;
        var_a0 += 1;
        var_v1 += 4;
    } while (var_a0 < 4U);
}
'''


def test_m2c_byte_step_becomes_the_counter_index():
    found = r.variants(DRAFT, 'f', ASM)
    assert [family for family, _ in found] == [r.FAMILY, r.FAMILY]
    typed, raw = (text for _, text in found)
    assert '*(&D_A + var_a0) = 0;' in typed and 'var_v1' not in typed
    assert '*((s32 *)((u8 *)&D_A + var_a0 * 4)) = 0;' in raw and 'var_v1' not in raw


def test_without_the_target_a_typed_step_is_read_as_c_elements():
    # `var_v1 += 4` on an s32 * is 16 bytes as C: the index is the counter's element at that stride
    found = r.variants(DRAFT, 'f')
    assert len(found) == 1 and '((u8 *)&D_A + var_a0 * 16)' in found[0][1]


def test_a_use_after_the_counter_step_reads_the_previous_index():
    source = DRAFT.replace('''        *var_v1 = 0;
        var_a0 += 1;
''', '''        var_a0 += 1;
        *var_v1 = 0;
''')
    typed = r.variants(source, 'f', ASM)[0][1]
    assert '*(&D_A + var_a0 - 1) = 0;' in typed


def test_refused_when_the_cursor_outlives_the_loop_or_steps_under_a_branch():
    after = DRAFT.replace('    } while (var_a0 < 4U);\n', '    } while (var_a0 < 4U);\n    *var_v1 = 1;\n')
    assert r.variants(after, 'f', ASM) == []
    branch = DRAFT.replace('        var_v1 += 4;\n', '        if (var_a0) {\n            var_v1 += 4;\n        }\n')
    assert r.variants(branch, 'f', ASM) == []
    jump = DRAFT.replace('        *var_v1 = 0;\n', '        if (*var_v1) continue;\n')
    assert r.variants(jump, 'f', ASM) == []


def test_the_loop_condition_sees_both_steps():
    source = '''extern u16 D_T[];

void f(void) {
    u16 *var_a1;
    s32 var_a0;

    var_a0 = 0;
    var_a1 = D_T;
    do {
        var_a0 += 1;
        var_a1 += 1;
    } while (*var_a1 != 0xFFFF);
}
'''
    typed = r.variants(source, 'f')[0][1]
    assert 'while (*(D_T + var_a0) != 0xFFFF);' in typed
