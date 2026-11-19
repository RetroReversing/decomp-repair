"""A call's argument count from the target's setup of the argument registers."""
from decomprepair import target_call_arity_repairs as t

SOURCE = '''void osCreateMesgQueue();
void g(s32, s32, s32);

void f(void) {
    osCreateMesgQueue(D_A, D_B, 8);
    osCreateMesgQueue(D_C, D_D);
    g(1, 2, 3);
}
'''
ASM = '''/* 0 */  lui        $a0, %hi(D_A)
/* 4 */  addiu      $a2, $zero, 0x8
/* 8 */  jal        func_800A1BB0
/* c */  nop
/* 10 */  addiu      $a2, $zero, 0x1
/* 14 */  jal        func_800A1BB0
/* 18 */  lui        $a0, %hi(D_C)
/* 1c */  addiu      $a0, $zero, 0x1
/* 20 */  jal        g
/* 24 */  addiu      $a1, $zero, 0x2
'''


def test_the_targets_calls():
    found = t.calls(ASM)
    assert [c for c, _ in found] == ['func_800A1BB0', 'func_800A1BB0', 'g']
    assert found[1][1] == {'a2': 1, 'a0': None} and found[2][1] == {'a0': 1, 'a1': 2}


def test_a_missing_constant_is_passed_and_an_unset_one_dropped():
    # An N64 function created a message queue with two arguments where the game set $a2 to 1.
    texts = [text for _, text in t.variants(SOURCE, 'f', ASM)]
    assert any('osCreateMesgQueue(D_C, D_D, 1);' in x for x in texts)
    dropped = [x for x in texts if '    g(1, 2);' in x]
    assert dropped and 'void g(s32, s32);' in dropped[0]


def test_left_alone_without_the_targets_calls():
    assert t.variants(SOURCE, 'f', '') == []
