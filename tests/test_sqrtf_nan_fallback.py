"""sqrtf_nan_fallback: m2c's `v = sqrtf(a); if (v != v) { fallback(a); }` is the compiler's builtin, not source."""
from decomprepair import registry
from decomprepair import sqrtf_nan_fallback as nan

SOURCE = '''f32 sqrtf(f32);
void func_80094350(f32);

void f(void *arg0) {
    f32 temp_fa0;
    f32 temp_fv0;

    temp_fa0 = M2C_FIELD(arg0, f32 *, 0) * M2C_FIELD(arg0, f32 *, 0);
    temp_fv0 = sqrtf(temp_fa0);
    if (temp_fv0 != temp_fv0) {
        func_80094350(temp_fa0);
    }
}
'''
ASM = '''glabel f
/* 0 80001000 C4840000 */  lwc1       $ft0, 0x0($a0)
/* 4 80001004 46042102 */  mul.s      $ft0, $ft0, $ft0
/* 8 80001008 46006004 */  sqrt.s     $fv0, $fa0
/* C 8000100C 46000032 */  c.eq.s     $fv0, $fv0
/* 10 80001010 00000000 */  nop
/* 14 80001014 45010003 */  bc1t       .L80001024
/* 18 80001018 00000000 */  nop
/* 1C 8000101C 0C0250D4 */  jal        func_80094350
/* 20 80001020 00000000 */  nop
.L80001024:
/* 24 80001024 03E00008 */  jr         $ra
/* 28 80001028 00000000 */  nop
endlabel f
'''


def test_the_retry_block_is_dropped_and_the_return_is_offered():
    out = dict(nan.variants(SOURCE, 'f', ASM))
    assert 'func_80094350(temp_fa0)' not in out[nan.FAMILY].split('void f(')[1]
    assert 'temp_fv0 = sqrtf(temp_fa0);\n}' in out[nan.FAMILY]
    assert 'f32 f(void *arg0) {' in out[nan.FAMILY + '_return'] and 'return temp_fv0;\n}' in out[nan.FAMILY + '_return']


def test_an_undeclared_sqrtf_gets_its_prototype_and_a_declared_one_does_not():
    bare = SOURCE.replace('f32 sqrtf(f32);\n', '')
    assert 'f32 sqrtf(f32);\n' in dict(nan.variants(bare, 'f', ASM))[nan.FAMILY]
    assert dict(nan.variants(bare, 'f', ASM, 'f32 sqrtf(f32);\n'))[nan.FAMILY].count('sqrtf(f32)') == 0


def test_a_retry_that_sets_a_copy_of_the_root_is_dropped_and_each_block_is_a_child():
    two = SOURCE.replace('    temp_fv0 = sqrtf(temp_fa0);\n', '''    temp_fv0 = sqrtf(temp_fa0);
    var = temp_fv0;
    if (temp_fv0 != temp_fv0) {
        var = func_80094350(temp_fa0);
    }
    temp_fv0 = sqrtf(var);
''')
    out = nan.variants(two, 'f', ASM)
    assert [f for f, _ in out].count(nan.FAMILY + '_one') == 2
    assert 'func_80094350' not in dict(out)[nan.FAMILY].split('void f(')[1]


def test_nothing_without_the_target_evidence_or_for_another_condition():
    assert nan.variants(SOURCE, 'f', ASM.replace('sqrt.s', 'add.s ')) == []
    assert nan.variants(SOURCE, 'f', ASM.replace('jal        func_80094350', 'jal        func_1')) == []
    assert nan.variants(SOURCE.replace('temp_fv0 != temp_fv0', 'temp_fv0 != temp_fa0'), 'f', ASM) == []
    assert nan.variants(SOURCE.replace('void f', 'f32 f'), 'f', ASM)[0][0] == nan.FAMILY
    assert nan.FAMILY + '_return' not in [f for f, _ in nan.variants(SOURCE.replace('void f', 'f32 f'), 'f', ASM)]


def test_the_return_is_not_offered_when_the_root_is_overwritten_before_the_exit():
    clobbered = ASM.replace('jr         $ra', 'add.s      $fv0, $fv1, $fv1\n/* 24 */  jr         $ra')
    assert nan.FAMILY + '_return' not in [f for f, _ in nan.variants(SOURCE, 'f', clobbered)]


def test_it_is_declared_in_the_registry():
    assert any(r.module == 'sqrtf_nan_fallback' for r in registry.declared())
