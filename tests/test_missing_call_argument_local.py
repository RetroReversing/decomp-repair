"""missing_call_argument_local: a call m2c left an argument short gets the local holding the value the target passes."""
from decomprepair import missing_call_argument_local as mcal
from decomprepair import registry

# An N64 function (KMC GCC 2.7.2) that loads a field into $a0, tests it, and passes it to a one-argument callee; the
# draft read the field into `temp_a0` and called the callee with nothing (10 -> 0 with the argument).
SOURCE = '''M2C_UNK release(void);                         /* extern */
extern s32 D_800B83B4;

s32 f(void *arg0) {
    s32 temp_a0;

    if (M2C_FIELD(arg0, s32 *, 0x68) == -1) {
        temp_a0 = M2C_FIELD(arg0, s32 *, 0xC4);
        if (temp_a0 != 0) {
            release();
            M2C_FIELD(arg0, s32 *, 0xC4) = 0;
        }
        D_800B83B4 += 1;
    }
    M2C_FIELD(arg0, s32 *, 0x68) = -1;
    return 1;
}
'''
ASM = '''glabel f
/* 0 80001000 00808021 */  addu       $s0, $a0, $zero
/* 4 80001004 8E030068 */  lw         $v1, 0x68($s0)
/* 8 80001008 1462000C */  bne        $v1, $v0, .L80001038
/* C 8000100C 2402FFFF */  addiu      $v0, $zero, -0x1
/* 10 80001010 8E0400C4 */  lw         $a0, 0xC4($s0)
/* 14 80001014 10800005 */  beqz       $a0, .L8000102C
/* 18 80001018 3C03800C */  lui        $v1, %hi(D_800B83B4)
/* 1C 8000101C 0C0094A0 */  jal        release
/* 20 80001020 00000000 */  nop
/* 24 80001024 AE0000C4 */  sw         $zero, 0xC4($s0)
'''
CALLEE = '''void release(void *arg0) {
    if (arg0 != NULL) {
        M2C_FIELD(arg0, s32 *, 4) = 0;
    }
}
'''


def _only(out):
    assert len(out) == 1
    family, text = out[0]
    assert family == mcal.FAMILY
    return text


def test_the_local_holding_the_loaded_field_is_passed_and_the_prototype_takes_it():
    text = _only(mcal.variants(SOURCE, 'f', ASM))
    assert 'release(temp_a0);' in text
    assert 'M2C_UNK release(s32);' in text


def test_the_callees_matched_definition_gives_the_prototype():
    text = _only(mcal.variants(SOURCE, 'f', ASM, callees=CALLEE))
    assert 'release(temp_a0);' in text
    assert 'M2C_UNK release(void *);' in text


def test_a_matched_definition_with_another_arity_gives_nothing():
    two = 'void release(void *arg0, s32 arg1) {\n}\n'
    assert mcal.variants(SOURCE, 'f', ASM, callees=two) == []


def test_a_header_declaring_another_arity_gives_nothing():
    assert mcal.variants(SOURCE, 'f', ASM, header='void release(void *, s32);') == []


def test_a_varargs_callee_gives_nothing():
    assert mcal.variants(SOURCE.replace('M2C_UNK release(void);', 'M2C_UNK release(s32, ...);'), 'f', ASM) == []


def test_a_local_written_again_between_the_load_and_the_call_is_not_offered():
    changed = SOURCE.replace('            release();', '            temp_a0 += 1;\n            release();')
    assert mcal.variants(changed, 'f', ASM) == []


def test_a_local_assigned_only_after_the_call_is_not_offered():
    changed = SOURCE.replace('''        temp_a0 = M2C_FIELD(arg0, s32 *, 0xC4);
        if (temp_a0 != 0) {''', '''        if (M2C_FIELD(arg0, s32 *, 0xC4) != 0) {''').replace(
        '            M2C_FIELD(arg0, s32 *, 0xC4) = 0;', '            temp_a0 = M2C_FIELD(arg0, s32 *, 0xC4);')
    assert mcal.variants(changed, 'f', ASM) == []


def test_a_call_the_target_sets_no_argument_for_is_left_alone():
    assert mcal.variants(SOURCE, 'f', ASM.replace('lw         $a0, 0xC4($s0)', 'lw         $v0, 0xC4($s0)')) == []


def test_a_constant_argument_is_target_call_arity_s_step():
    assert mcal.variants(SOURCE, 'f', ASM.replace('lw         $a0, 0xC4($s0)', 'addiu      $a0, $zero, 0x5')) == []


def test_a_call_made_a_different_number_of_times_gives_nothing():
    changed = SOURCE.replace('        D_800B83B4 += 1;', '        D_800B83B4 += 1;\n        release();')
    assert mcal.variants(changed, 'f', ASM) == []


def test_an_argument_copied_from_a_register_goes_by_m2cs_register_name():
    source = '''void sink(void);
s32 g(void);

void f(s32 arg0) {
    s32 var_a1;
    s32 temp_v0;

    temp_v0 = g();
    var_a1 = temp_v0 + arg0;
    sink();
}
'''
    asm = '''glabel f
/* 0 80001000 0C000400 */  jal        g
/* 4 80001004 00000000 */  nop
/* 8 80001008 00512821 */  addu       $a1, $v0, $s1
/* C 8000100C 00002021 */  addu       $a0, $zero, $zero
/* 10 80001010 0C000500 */  jal        sink
/* 14 80001014 00000000 */  nop
'''
    # $a0 is a constant (0), as target_call_arity reads it, and $a1 the value m2c kept in `var_a1`
    text = _only(mcal.variants(source, 'f', asm))
    assert 'sink(0, var_a1);' in text and 'void sink(s32, s32);' in text


def test_it_declares_itself_with_optional_callees():
    repair = registry.get('missing_call_argument_local')
    assert repair is not None and registry.problems(repair) == []
    assert 'callees' in repair.needs and 'callees' in registry.OPTIONAL
    assert repair.arguments({'source': SOURCE, 'name': 'f', 'asm': ASM, 'header': ''}) == {
        'source': SOURCE, 'name': 'f', 'asm': ASM, 'header': ''}
    assert registry.run('missing_call_argument_local', source=SOURCE, name='f', asm=ASM, header='', callees=CALLEE)
