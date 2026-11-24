"""untouched_slot_passthrough: an argument register the target leaves alone before one of several calls is the caller's own."""
from decomprepair import registry
from decomprepair import untouched_slot_passthrough as usp

# An N64 function (KMC GCC 2.7.2): an early-return arm sets only $a1 before calling a two-argument callee (the caller's
# `$a0` still its own, reached through branches), the tail calls it with both set; m2c drafted the early call as
# `go((void *)1)` (5 -> 0 with `go(arg0, 1)`).
SOURCE = '''M2C_UNK go();
M2C_UNK other();
extern s32 D_80100000;

void f(void *arg0) {
    if (M2C_FIELD(arg0, s32 *, 0x7C) != 0) {
        if (D_80100000 == 0) {
            go((void *)1);
            return;
        }
        other();
    }
    if (other() != 0) {
        go(arg0, 1);
    }
}
'''
ASM = '''glabel f
/* 0 80001000 27BDFFE0 */  addiu      $sp, $sp, -0x20
/* 4 80001004 AFB10014 */  sw         $s1, 0x14($sp)
/* 8 80001008 00808821 */  addu       $s1, $a0, $zero
/* C 8000100C AFBF0018 */  sw         $ra, 0x18($sp)
/* 10 80001010 8E22007C */  lw         $v0, 0x7C($s1)
/* 14 80001014 10400009 */  beqz       $v0, .L1
/* 18 80001018 3C028010 */  lui        $v0, %hi(D_80100000)
/* 1C 8000101C 8C420000 */  lw         $v0, %lo(D_80100000)($v0)
/* 20 80001020 14400005 */  bnez       $v0, .L2
/* 24 80001024 00000000 */  nop
/* 28 80001028 0C00C310 */  jal        go
/* 2C 8000102C 24050001 */  addiu      $a1, $zero, 0x1
/* 30 80001030 0800C523 */  j          .L3
/* 34 80001034 00000000 */  nop
.L2:
/* 38 80001038 0C00C311 */  jal        other
/* 3C 8000103C 00000000 */  nop
.L1:
/* 40 80001040 0C00C311 */  jal        other
/* 44 80001044 00000000 */  nop
/* 48 80001048 1040000A */  beqz       $v0, .L3
/* 4C 8000104C 00000000 */  nop
/* 50 80001050 02202021 */  addu       $a0, $s1, $zero
/* 54 80001054 0C00C310 */  jal        go
/* 58 80001058 24050001 */  addiu      $a1, $zero, 0x1
.L3:
/* 5C 8000105C 8FBF0018 */  lw         $ra, 0x18($sp)
/* 60 80001060 8FB10014 */  lw         $s1, 0x14($sp)
/* 64 80001064 03E00008 */  jr         $ra
/* 68 80001068 27BD0020 */  addiu      $sp, $sp, 0x20
'''


def _texts(source=SOURCE, asm=ASM, **kw):
    return [text for family, text in usp.variants(source, 'f', asm, **kw)]


def test_the_early_call_passes_the_callers_own_argument_first():
    texts = _texts()
    assert texts[0].count('go(arg0, 1);') == 2 and 'go((void *)1' not in texts[0]
    assert 'go(arg0, (void *)1);' in texts[1]  # the cast kept, as the second child
    assert all(family == usp.FAMILY for family, _ in usp.variants(SOURCE, 'f', ASM))


def test_the_call_the_target_wrote_both_registers_for_is_left_alone():
    assert all('        go(arg0, 1);\n    }\n}' in text for text in _texts())


def test_a_register_written_on_a_route_to_the_call_is_not_the_callers():
    asm = ASM.replace('/* 18 80001018 3C028010 */', '/* 16 80001016 00002021 */  addu       $a0, $zero, $zero\n'
                                                     '/* 18 80001018 3C028010 */')
    assert _texts(asm=asm) == []


def test_a_call_count_that_differs_from_the_targets_gives_nothing():
    assert _texts(SOURCE.replace('        other();\n    }\n', '    }\n').replace('go(arg0, 1);', 'go(arg0, 1);\n        go(arg0, 1);')) == []


def test_a_callee_with_another_number_of_parameters_gives_nothing():
    assert _texts(callees='void go(s32 arg0) {\n}\n') == []
    assert _texts(header='void go(s32, s32, s32);') == []
    assert _texts(SOURCE.replace('M2C_UNK go();', 'M2C_UNK go(s32);')) == []


def test_a_parameter_the_body_assigns_is_not_passed_on():
    assert _texts(SOURCE.replace('        other();\n    }\n', '        arg0 = 0;\n    }\n')) == []


def test_a_caller_without_the_parameter_gains_it():
    source = SOURCE.replace('void f(void *arg0)', 'void f(void)').replace('M2C_FIELD(arg0, s32 *, 0x7C) != 0', 'D_80100000 != 3').replace('go(arg0, 1)', 'go(1, 1)')
    texts = _texts(source)
    assert texts and 'void f(s32 arg0) {' in texts[0] and 'go(arg0, 1);' in texts[0]


def test_the_family_is_registered():
    repair = registry.get('untouched_slot_passthrough')
    assert repair is not None and registry.problems(repair) == []
    assert registry.run('untouched_slot_passthrough', source=SOURCE, name='f', asm=ASM, header='', callees='')
