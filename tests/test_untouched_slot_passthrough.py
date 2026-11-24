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


# A constant the game's code sets up once, before a branch, for the call on one arm (`$a1`, with the caller's own
# `$a0` untouched). m2c drafted it as the wrong slot of that call, `go((void *)0x21, 0x80)`, and as the only argument
# of the other arm's call, `stop(0x21)`. The passthrough alone adds a stray `$a0` set-up to `stop` and scores worse
# (10 -> 100 on an N64 function, KMC GCC 2.7.2); with `stop`'s argument gone it is exact (10 -> 0). The calls on the
# else arm are one `jal` in the target (both arms' calls joined), three C calls against two `jal`s.
ARMS = '''M2C_UNK other(M2C_UNK, M2C_UNK);
M2C_UNK stop(M2C_UNK);
M2C_UNK join();
M2C_UNK go();
extern s32 D_A;
extern s32 D_B;
extern s32 D_C;

s32 f(void *arg0) {
    if (((u32 *) &D_A)[M2C_FIELD(arg0, s32 *, 0xB0)] & 0x4000) {
        if (((u32 *) &D_B)[M2C_FIELD(arg0, s32 *, 0xB0)] & 0x2000) {
            go((void *)0x21, 0x80);
            other(0xC, 0x80);
            join();
            return 1;
        }
        D_C = 0;
        stop(0x21);
        if (M2C_FIELD(arg0, s32 *, 0x78) != 0) {
            go(arg0, 0xD, 0x80);
        } else {
            go(arg0, 0x13, 0x80);
        }
        return 1;
    }
    return 0;
}
'''
ARMS_ASM = '''glabel f
/* 0 80001000 27BDFFE8 */  addiu      $sp, $sp, -0x18
/* 4 80001004 AFB00010 */  sw         $s0, 0x10($sp)
/* 8 80001008 00808021 */  addu       $s0, $a0, $zero
/* C 8000100C 3C028010 */  lui        $v0, %hi(D_A)
/* 10 80001010 AFBF0014 */  sw         $ra, 0x14($sp)
/* 14 80001014 8E0300B0 */  lw         $v1, 0xB0($s0)
/* 18 80001018 24420000 */  addiu      $v0, $v0, %lo(D_A)
/* 1C 8000101C 00031880 */  sll        $v1, $v1, 2
/* 20 80001020 00621021 */  addu       $v0, $v1, $v0
/* 24 80001024 8C420000 */  lw         $v0, 0x0($v0)
/* 28 80001028 30424000 */  andi       $v0, $v0, 0x4000
/* 2C 8000102C 10400020 */  beqz       $v0, .Lend
/* 30 80001030 3C028010 */   lui       $v0, %hi(D_B)
/* 34 80001034 24420000 */  addiu      $v0, $v0, %lo(D_B)
/* 38 80001038 00621021 */  addu       $v0, $v1, $v0
/* 3C 8000103C 8C420000 */  lw         $v0, 0x0($v0)
/* 40 80001040 30422000 */  andi       $v0, $v0, 0x2000
/* 44 80001044 1040000A */  beqz       $v0, .Lelse
/* 48 80001048 24050021 */   addiu     $a1, $zero, 0x21
/* 4C 8000104C 0C010000 */  jal        go
/* 50 80001050 24060080 */   addiu     $a2, $zero, 0x80
/* 54 80001054 2404000C */  addiu      $a0, $zero, 0xC
/* 58 80001058 0C010001 */  jal        other
/* 5C 8000105C 24050080 */   addiu     $a1, $zero, 0x80
/* 60 80001060 0C010002 */  jal        join
/* 64 80001064 00000000 */   nop
/* 68 80001068 08000000 */  j          .Lret
/* 6C 8000106C 24020001 */   addiu     $v0, $zero, 0x1
.Lelse:
/* 70 80001070 3C028010 */  lui        $v0, %hi(D_C)
/* 74 80001074 0C010003 */  jal        stop
/* 78 80001078 AC400000 */   sw        $zero, %lo(D_C)($v0)
/* 7C 8000107C 8E020078 */  lw         $v0, 0x78($s0)
/* 80 80001080 10400003 */  beqz       $v0, .Lb
/* 84 80001084 02002021 */   addu      $a0, $s0, $zero
/* 88 80001088 08000000 */  j          .Lc
/* 8C 8000108C 2405000D */   addiu     $a1, $zero, 0xD
.Lb:
/* 90 80001090 24050013 */  addiu      $a1, $zero, 0x13
.Lc:
/* 94 80001094 0C010000 */  jal        go
/* 98 80001098 24060080 */   addiu     $a2, $zero, 0x80
/* 9C 8000109C 08000000 */  j          .Lret
/* A0 800010A0 24020001 */   addiu     $v0, $zero, 0x1
.Lend:
/* A4 800010A4 00001021 */  addu       $v0, $zero, $zero
.Lret:
/* A8 800010A8 8FBF0014 */  lw         $ra, 0x14($sp)
/* AC 800010AC 8FB00010 */  lw         $s0, 0x10($sp)
/* B0 800010B0 03E00008 */  jr         $ra
/* B4 800010B4 27BD0018 */   addiu     $sp, $sp, 0x18
'''


def test_the_constant_drafted_as_two_calls_arguments_is_dropped_from_the_other_call_in_the_same_child():
    texts = _texts(ARMS, ARMS_ASM)
    both = [t for t in texts if 'stop();' in t and 'go(arg0, 0x21, 0x80);' in t]
    assert both and 'M2C_UNK stop(void);' in both[0] and 'stop(0x21)' not in both[0]
    assert any('stop(0x21);' in t and 'go(arg0, 0x21, 0x80);' in t for t in texts)  # the passthrough alone, as before
    assert all(family == usp.FAMILY for family, _ in usp.variants(ARMS, 'f', ARMS_ASM))


def test_a_call_the_target_writes_nothing_different_for_keeps_its_argument_when_it_is_not_the_same_constant():
    texts = _texts(ARMS.replace('stop(0x21)', 'stop(0x22)'), ARMS_ASM)
    assert texts and all('stop(0x22);' in t for t in texts)


def test_an_extra_call_that_is_not_the_other_arm_of_an_else_gives_nothing():
    source = ARMS.replace('        if (M2C_FIELD(arg0, s32 *, 0x78) != 0) {\n            go(arg0, 0xD, 0x80);\n        } else {\n'
                          '            go(arg0, 0x13, 0x80);\n        }\n',
                          '        go(arg0, 0xD, 0x80);\n        go(arg0, 0x13, 0x80);\n')
    assert _texts(source, ARMS_ASM) == []
