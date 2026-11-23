"""returned_register_local: return the local that lives in the register the target's epilogue copies into $v0."""
from decomprepair import registry
from decomprepair import returned_register_local as rrl

# An N64 function (KMC GCC 2.7.2) that makes an object, sets it up and returns it; the saved best returned a field it had
# loaded instead (10 -> 0 returning the object).
SOURCE = '''void *make(s32, s32);
s32 use(s32, f32);
s32 setup(void *, s32);
extern s32 handler;

s32 f(s32 arg0) {
    s32 temp_s1;
    void *temp_s0;

    temp_s0 = make(0x1C, 0);
    temp_s1 = (*(s32 *)((s8 *)temp_s0 + 0xE0));
    use(temp_s1, 1.0f);
    (*(s32 *)((s8 *)temp_s0 + 0)) = 0x101B;
    setup(temp_s0, arg0);
    (*(s32 **)((s8 *)temp_s0 + 0x9C)) = &handler;

return temp_s1;
}
'''
ASM = '''glabel f
/* 0 80001000 27BDFFE0 */  addiu      $sp, $sp, -0x20
/* 4 80001004 AFB20018 */  sw         $s2, 0x18($sp)
/* 8 80001008 00809021 */  addu       $s2, $a0, $zero
/* C 8000100C 0C010BC0 */  jal        make
/* 10 80001010 2404001C */  addiu      $a0, $zero, 0x1C
/* 14 80001014 00408021 */  addu       $s0, $v0, $zero
/* 18 80001018 8E1100E0 */  lw         $s1, 0xE0($s0)
/* 1C 8000101C 0C0214B3 */  jal        setup
/* 20 80001020 02402821 */  addu       $a1, $s2, $zero
/* 24 80001024 02001021 */  addu       $v0, $s0, $zero
/* 28 80001028 3C038007 */  lui        $v1, %hi(handler)
/* 2C 8000102C 24637E80 */  addiu      $v1, $v1, %lo(handler)
/* 30 80001030 AC43009C */  sw         $v1, 0x9C($v0)
/* 34 80001034 8FBF001C */  lw         $ra, 0x1C($sp)
/* 38 80001038 8FB00010 */  lw         $s0, 0x10($sp)
/* 3C 8000103C 03E00008 */  jr         $ra
/* 40 80001040 27BD0020 */  addiu      $sp, $sp, 0x20
'''


def test_the_epilogues_register_names_the_local_to_return_cast_to_the_declared_type():
    out = rrl.variants(SOURCE, 'f', ASM)
    assert out and out[0][0] == rrl.FAMILY
    assert 'return (s32) temp_s0;' in out[0][1]
    assert 's32 f(s32 arg0) {' in out[0][1]  # the callers' type stays


def test_the_register_is_read_through_move_and_or():
    for copy in ('move       $v0, $s0', 'or         $v0, $zero, $s0'):
        assert rrl.returned_register(ASM.replace('addu       $v0, $s0, $zero', copy)) == 's0'


def test_a_parameter_copied_into_the_register_is_offered():
    asm = ASM.replace('addu       $v0, $s0, $zero', 'addu       $v0, $s2, $zero')
    out = rrl.variants(SOURCE, 'f', asm)
    assert any('return arg0;' in text for _, text in out)


def test_nothing_when_the_draft_already_returns_the_registers_local():
    assert rrl.variants(SOURCE.replace('return temp_s1;', 'return (s32) temp_s0;'), 'f', ASM) == []


def test_nothing_for_a_narrow_or_float_return_type():
    for kind in ('s16', 'u8', 'f32', 'void'):
        assert rrl.variants(SOURCE.replace('s32 f(s32 arg0)', f'{kind} f(s32 arg0)'), 'f', ASM) == []


def test_nothing_with_more_than_one_return():
    two = SOURCE.replace('    temp_s1 = (*', '    if (temp_s0 == 0) {\n        return 0;\n    }\n    temp_s1 = (*')
    assert rrl.variants(two, 'f', ASM) == []


def test_nothing_when_v0_is_loaded_set_to_a_constant_or_a_calls_result():
    for write in ('lw         $v0, 0x4($s0)', 'addiu      $v0, $zero, 0x1'):
        assert rrl.variants(SOURCE, 'f', ASM.replace('addu       $v0, $s0, $zero', write)) == []
    result = ASM.replace('/* 24 80001024 02001021 */  addu       $v0, $s0, $zero\n', '')
    assert rrl.variants(SOURCE, 'f', result) == []


def test_nothing_with_a_branch_between_the_copy_and_the_return():
    asm = ASM.replace('/* 28 80001028 3C038007 */', '/* 26 80001026 10400002 */  beqz       $v0, .L1\n'
                                                     '/* 28 80001028 3C038007 */')
    assert rrl.variants(SOURCE, 'f', asm) == []


def test_it_declares_itself():
    repair = registry.get('returned_register_local')
    assert repair is not None and registry.problems(repair) == []
    assert registry.run('returned_register_local', source=SOURCE, name='f', asm=ASM)
