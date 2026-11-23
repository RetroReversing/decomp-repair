"""untouched_argument_parameter: a middle argument the target never sets is the caller's own, passed on."""
from decomprepair import registry
from decomprepair import untouched_argument_parameter as uap

# An N64 function (KMC GCC 2.7.2) loading two fields of a table entry into $a0 and $a2 and leaving $a1 alone before a
# three-argument callee; the saved best passed two arguments (5 -> 0 with the caller's own second argument).
SOURCE = '''s32 load(s32, s32);
extern char D_800B383C[];

void f(s32 arg0) {
    void *temp_v0;

    temp_v0 = (arg0 * 0xC) + D_800B383C;
    load(M2C_FIELD(temp_v0, s32 *, 0), M2C_FIELD(temp_v0, s32 *, 8));
}
'''
ASM = '''glabel f
/* 0 80001000 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 4 80001004 3C03800B */  lui        $v1, %hi(D_800B383C)
/* 8 80001008 2463383C */  addiu      $v1, $v1, %lo(D_800B383C)
/* C 8000100C 00041040 */  sll        $v0, $a0, 1
/* 10 80001010 00441021 */  addu       $v0, $v0, $a0
/* 14 80001014 00021080 */  sll        $v0, $v0, 2
/* 18 80001018 00431021 */  addu       $v0, $v0, $v1
/* 1C 8000101C AFBF0010 */  sw         $ra, 0x10($sp)
/* 20 80001020 8C440000 */  lw         $a0, 0x0($v0)
/* 24 80001024 8C460008 */  lw         $a2, 0x8($v0)
/* 28 80001028 0C00AD04 */  jal        load
/* 2C 8000102C 00000000 */  nop
/* 30 80001030 8FBF0010 */  lw         $ra, 0x10($sp)
/* 34 80001034 03E00008 */  jr         $ra
/* 38 80001038 27BD0018 */  addiu      $sp, $sp, 0x18
'''
CALLEE = 'void load(s32 arg0, void *arg1, s32 arg2) {\n}\n'


def _only(out):
    assert len(out) == 1 and out[0][0] == uap.FAMILY
    return out[0][1]


def test_the_untouched_middle_register_is_the_callers_own_argument():
    text = _only(uap.variants(SOURCE, 'f', ASM))
    assert 'void f(s32 arg0, s32 arg1) {' in text
    assert 'load(M2C_FIELD(temp_v0, s32 *, 0), arg1, M2C_FIELD(temp_v0, s32 *, 8));' in text
    assert 's32 load(s32, s32, s32);' in text


def test_the_callees_matched_definition_gives_the_declaration():
    text = _only(uap.variants(SOURCE, 'f', ASM, callees=CALLEE))
    assert 's32 load(s32, void *, s32);' in text


def test_an_unprototyped_callee_keeps_its_declaration():
    text = _only(uap.variants(SOURCE.replace('s32 load(s32, s32);', 's32 load();'), 'f', ASM))
    assert 's32 load();' in text and 'arg1, M2C' in text


def test_a_caller_that_has_the_parameter_is_passthrough_arguments_step():
    assert uap.variants(SOURCE.replace('void f(s32 arg0)', 'void f(s32 arg0, s32 arg1)'), 'f', ASM) == []


def test_a_register_written_before_the_call_is_not_the_callers():
    asm = ASM.replace('/* 1C 8000101C AFBF0010 */', '/* 1A 8000101A 00002821 */  addu       $a1, $zero, $zero\n'
                                                     '/* 1C 8000101C AFBF0010 */')
    assert uap.variants(SOURCE, 'f', asm) == []


def test_a_branch_before_the_call_ends_the_proof():
    asm = ASM.replace('/* 1C 8000101C AFBF0010 */', '/* 1A 8000101A 10800002 */  beqz       $a0, .L1\n'
                                                     '/* 1C 8000101C AFBF0010 */')
    assert uap.variants(SOURCE, 'f', asm) == []


def test_a_matched_definition_or_header_with_another_arity_gives_nothing():
    assert uap.variants(SOURCE, 'f', ASM, callees='void load(s32 arg0, s32 arg1) {\n}\n') == []
    assert uap.variants(SOURCE, 'f', ASM, header='s32 load(s32, s32, s32, s32);') == []


def test_a_header_declaring_the_caller_with_its_present_parameters_gives_nothing():
    assert uap.variants(SOURCE, 'f', ASM, header='void f(s32);') == []
    assert _only(uap.variants(SOURCE, 'f', ASM, header='void f(s32, s32);'))


def test_varargs_gives_nothing():
    assert uap.variants(SOURCE.replace('s32 load(s32, s32);', 's32 load(s32, ...);'), 'f', ASM) == []


def test_a_call_with_as_many_arguments_as_the_target_sets_is_left_alone():
    three = SOURCE.replace('load(M2C_FIELD(temp_v0, s32 *, 0), ', 'load(M2C_FIELD(temp_v0, s32 *, 0), 0, ')
    assert uap.variants(three, 'f', ASM) == []


def test_it_declares_itself():
    repair = registry.get('untouched_argument_parameter')
    assert repair is not None and registry.problems(repair) == []
    assert registry.run('untouched_argument_parameter', source=SOURCE, name='f', asm=ASM, header='', callees='')
