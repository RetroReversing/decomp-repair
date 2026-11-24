"""void_parameter_return: a `void` draft whose target returns its incoming parameter in $v0 is declared to return it."""
from decomprepair import registry
from decomprepair import void_parameter_return as vpr

# A vector helper (KMC GCC 2.7.2, N64): `dst = a + b` with the destination copied into $v0 ahead of its first store.
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))

void f(void *arg0, void *arg1, void *arg2) {
    M2C_FIELD(arg0, f32 *, 0) = (f32) (M2C_FIELD(arg1, f32 *, 0) + M2C_FIELD(arg2, f32 *, 0));
    M2C_FIELD(arg0, f32 *, 4) = (f32) (M2C_FIELD(arg1, f32 *, 4) + M2C_FIELD(arg2, f32 *, 4));
}
'''
ASM = '''glabel f
/* 0 80001000 C4A00000 */  lwc1       $fv0, 0x0($a1)
/* 4 80001004 C4C20000 */  lwc1       $fv1, 0x0($a2)
/* 8 80001008 46020000 */  add.s      $fv0, $fv0, $fv1
/* C 8000100C 00801021 */  addu       $v0, $a0, $zero
/* 10 80001010 E4400000 */  swc1       $fv0, 0x0($v0)
/* 14 80001014 C4A00004 */  lwc1       $fv0, 0x4($a1)
/* 18 80001018 C4C20004 */  lwc1       $fv1, 0x4($a2)
/* 1C 8000101C 46020000 */  add.s      $fv0, $fv0, $fv1
/* 20 80001020 03E00008 */  jr         $ra
/* 24 80001024 E4400004 */  swc1       $fv0, 0x4($v0)
endlabel f
'''


def test_the_returned_parameter_is_read_from_the_epilogue():
    assert vpr.incoming_parameter(ASM) == 0
    assert vpr.incoming_parameter(ASM.replace('addu       $v0, $a0, $zero', 'move       $v0, $a0')) == 0
    assert vpr.incoming_parameter(ASM.replace('$v0, $a0, $zero', '$v0, $zero, $a2')) == 2


def test_a_void_draft_is_offered_the_pointer_and_the_word_return():
    out = vpr.variants(SOURCE, 'f', ASM)
    assert [family for family, _ in out] == [vpr.FAMILY, vpr.FAMILY]
    pointer, word = (text for _, text in out)
    assert 'void * f(void *arg0, void *arg1, void *arg2) {' in pointer and pointer.rstrip().endswith('return arg0;\n}')
    assert 's32 f(void *arg0, void *arg1, void *arg2) {' in word and 'return (s32) arg0;\n}' in word


def test_a_word_parameter_is_returned_without_a_cast():
    source = SOURCE.replace('void *arg0', 's32 arg0')
    out = vpr.variants(source, 'f', ASM)
    assert len(out) == 1 and 'return arg0;' in out[0][1] and 's32 f(s32 arg0' in out[0][1]


def test_no_child_without_the_evidence_or_for_a_value_function():
    assert vpr.variants(SOURCE.replace('void f', 's32 f'), 'f', ASM) == []
    assert vpr.variants(SOURCE.replace('void f', 'void *f'), 'f', ASM) == []
    assert vpr.variants(SOURCE, 'f', ASM.replace('addu       $v0, $a0, $zero', 'addu       $v0, $s0, $zero')) == []
    assert vpr.variants(SOURCE, 'f', ASM.replace('addu       $v0, $a0, $zero', 'lw         $v0, 0x0($a0)')) == []
    called = ASM.replace('/* 0 80001000', '/* 0 80001000 0C000000 */  jal        g\n/* 0 80001000', 1)
    assert vpr.incoming_parameter(called) is None  # a call before the copy: $a0 is no longer the caller's


def test_a_register_written_before_the_copy_is_not_the_incoming_parameter():
    written = ASM.replace('/* 0 80001000', '/* 0 80001000 24840004 */  addiu      $a0, $a0, 4\n/* 0 80001000', 1)
    assert vpr.incoming_parameter(written) is None


def test_a_branch_target_between_the_copy_and_the_return_declines():
    labelled = ASM.replace('/* 14 80001014', '.L80001014:\n/* 14 80001014')
    assert vpr.incoming_parameter(labelled) is None


def test_a_parameter_the_body_changes_declines():
    assert vpr.variants(SOURCE.replace('    M2C_FIELD(arg0, f32 *, 0)', '    arg0 += 4;\n    M2C_FIELD(arg0, f32 *, 0)', 1),
                        'f', ASM) == []
    assert vpr.variants(SOURCE.replace('    M2C_FIELD(arg0, f32 *, 0)', '    arg0 = arg1;\n    M2C_FIELD(arg0, f32 *, 0)', 1),
                        'f', ASM) == []


def test_a_float_or_wide_parameter_before_the_register_declines():
    assert vpr.variants(SOURCE.replace('void *arg0', 'f32 arg0'), 'f', ASM) == []
    assert vpr.variants(SOURCE.replace('void *arg0, ', 's64 arg0, '), 'f', ASM) == []


def test_a_header_prototype_that_says_void_is_left_alone():
    assert vpr.variants(SOURCE, 'f', ASM, 'void f(void *, void *, void *);\n') == []
    assert vpr.variants(SOURCE, 'f', ASM, 'void g(void);\n')


def test_bare_returns_and_an_earlier_prototype_follow_the_new_type():
    source = '''void f(void *arg0, void *arg1, void *arg2);

void f(void *arg0, void *arg1, void *arg2) {
    if (arg1 == 0) {
        return;
    }
    *(f32 *) arg0 = *(f32 *) arg1;
}
'''
    word = vpr.variants(source, 'f', ASM)[1][1]
    assert word.startswith('s32 f(void *arg0, void *arg1, void *arg2);')
    assert word.count('return (s32) arg0;') == 2
    assert word.rstrip().endswith('return (s32) arg0;\n}')


def test_a_body_that_already_ends_in_the_return_gets_no_second_one():
    source = SOURCE.rstrip()[:-1] + '    return;\n}\n'
    word = vpr.variants(source, 'f', ASM)[1][1]
    assert word.count('return (s32) arg0;') == 1


def test_a_trailing_conditional_return_still_gets_a_final_one():
    source = SOURCE.rstrip()[:-1] + '    if (arg1 == 0) return;\n}\n'
    word = vpr.variants(source, 'f', ASM)[1][1]
    assert word.count('return (s32) arg0;') == 2


def test_the_module_declares_itself_to_the_registry():
    declared = {repair.module: repair for repair in registry.declared()}
    assert declared['void_parameter_return'].needs == ('source', 'name', 'asm', 'header')
    assert 'void_parameter_return' in declared['void_parameter_return'].families
