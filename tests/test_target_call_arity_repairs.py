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


CONSUMED = '''void put(void);
void pick(s32);
extern u8 D_X;
extern u8 D_Y;

void f(void) {
    D_Y = D_X;
    put(D_X);
    pick(D_X);
}
'''
CONSUMED_ASM = '''/* 0 */  lui        $a0, %hi(D_X)
/* 4 */  lbu        $a0, %lo(D_X)($a0)
/* 8 */  lui        $at, %hi(D_Y)
/* c */  sb         $a0, %lo(D_Y)($at)
/* 10 */  jal        put
/* 14 */  nop
/* 18 */  lui        $a0, %hi(D_X)
/* 1c */  lbu        $a0, %lo(D_X)($a0)
/* 20 */  addiu      $v0, $zero, 0x3
/* 24 */  beq        $a0, $v0, .L1
/* 28 */  nop
/* 2c */  jal        pick
/* 30 */  nop
.L1:
'''


def test_a_value_stored_or_compared_before_a_call_may_be_a_leftover():
    # Three N64 functions passed m2c's leftover $a0 (a byte just stored, a switch's selector) to a callee that took
    # fewer arguments; dropping it was exact.
    assert t.calls(CONSUMED_ASM)[0][1] == {'a0': 'D_X'}
    assert t.calls(CONSUMED_ASM, consumed=True) == [('put', {}), ('pick', {})]
    texts = [text for _, text in t.variants(CONSUMED, 'f', CONSUMED_ASM)]
    assert any('    put();' in x for x in texts) and any('    pick();' in x for x in texts)


def test_a_store_through_an_argument_keeps_it_an_argument():
    asm = '''/* 0 */  lw         $a0, 0x6C($s0)
/* 4 */  sw         $v0, 0xC($a0)
/* 8 */  jal        put
/* c */  nop
'''
    assert t.calls(asm, consumed=True) == [('put', {'a0': None})]
