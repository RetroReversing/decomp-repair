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


THROUGH = '''void put();
void f(void *p) {
    void *r = *(void **)p;
    *(int *)((char *)r + 0x28) = 1;
    put(3, r);
}
'''
THROUGH_ASM = '''/* 0 */  lw         $a1, 0x0($s1)
/* 4 */  lw         $v1, 0x28($a1)
/* 8 */  addiu      $a0, $zero, 0x3
/* c */  jal        put
/* 10 */  sw         $v1, 0x28($a1)
'''


def test_a_pointer_loaded_through_an_argument_register_may_not_be_an_argument():
    # A record pointer held in $a1 and dereferenced twice, then a one-argument call: the draft passed $a1, and the
    # stray argument register changed the first scheduler's order in the next call's argument setup.
    assert t.calls(THROUGH_ASM)[0][1] == {'a0': 3}
    texts = [text for _, text in t.variants(THROUGH, 'f', THROUGH_ASM)]
    assert any('put(3);' in x for x in texts)


MERGED = '''void put();
void other();
void f(void *p, int a) {
    void *r = *(void **)p;
    *(int *)((char *)r + 0x28) = 1;
    put(3, r);
    other(3, r);
    wrap(get(a, r), r);
}
'''
MERGED_ASM = '''/* 0 */  lw         $a1, 0x0($s1)
/* 4 */  lw         $v1, 0x28($a1)
/* 8 */  addiu      $a0, $zero, 0x3
/* c */  jal        put
/* 10 */  sw         $v1, 0x28($a1)
/* 14 */  lw         $a1, 0x4($s1)
/* 18 */  lw         $v0, 0x28($a1)
/* 1c */  jal        other
/* 20 */  addiu      $a0, $zero, 0x3
/* 24 */  lw         $a1, 0x0($s1)
/* 28 */  sw         $v0, 0x10($a1)
/* 2c */  jal        renamedget
/* 30 */  lbu        $a0, 0x8($s2)
/* 34 */  jal        renamedwrap
/* 38 */  andi       $a0, $v0, 0xFFFF
'''


def test_every_callee_loses_the_stray_argument_together_and_nested_calls_pair_in_evaluation_order():
    # One callee's change alone leaves the first scheduler's argument-register order as it was (60 against 60 on the
    # function this came from); all three together were exact. The assembly renamed the inner and outer callee.
    texts = [text for _, text in t.variants(MERGED, 'f', MERGED_ASM)]
    both = [x for x in texts if 'put(3);' in x and 'other(3);' in x and 'wrap(get(a))' in x]
    assert both


def test_drops_only_extra_global_pointer_when_other_call_already_has_the_target_arity():
    source = """extern void *state;
int g();
void f(int value) {
    int saved = g(1);
    g(saved, state);
}
"""
    asm = """addiu $a0, $zero, 1
jal g
nop
move $a0, $s0
jal g
nop
"""
    candidates = [text for _, text in t.variants(source, 'f', asm)]
    assert any('saved = g(1);' in text and 'g(saved);' in text for text in candidates)
    assert not any('g(saved);' in text for _, text in t.variants(
        source.replace('g(saved, state)', 'g(saved, get())'), 'f', asm))
    assert not any('g(saved);' in text for _, text in t.variants(
        source.replace('extern void *state;', 'extern volatile void *state;'), 'f', asm))
    assert not any('g(saved);' in text for _, text in t.variants(
        '#define state get()\n' + source, 'f', asm))


def test_measured_three_argument_call_offers_dropping_forwarded_pointer():
    source = """s32 check(void *owner, u16, u16, u16);
s32 run(void *owner, u16 x, u16 y, u16 z) {
    return check(owner, x, y, z);
}
"""
    assembly = """jal prepare
nop
move $a0, $s0
move $a1, $s1
jal check
move $a2, $s2
"""
    expected = source.replace('check(void *owner, ', 'check(').replace('check(owner, ', 'check(')
    alternatives = t.variants(source, 'run', assembly)
    assert alternatives[0] == (t.FAMILY, expected)
    assert 'check(owner, x, y)' in alternatives[1][1]
    assert (t.FAMILY, expected) not in t.variants(source, 'run', assembly.replace('nop', 'nop\nmove $a3, $s4'))
    assert (t.FAMILY, expected) not in t.variants(source.replace('check(owner,', 'check(next(),'), 'run', assembly)


def test_measured_call_drop_prioritizes_a_consumed_literal():
    from decomprepair import target_call_arity_repairs as repair

    source = 's32 convert(s32, s32);\nvoid f(s32 *p) { *p = convert(*p, 0x1000040); }\n'
    target = ['lui $a1, 0x100', 'ori $a1, $a1, 0x40', 'or $v0, $v0, $a1',
              'jal convert', 'addu $a0, $a0, $v0']
    candidate = ['lui $a1, 0x100', 'ori $a1, $a1, 0x40', 'or $v0, $v0, $a2',
                 'jal convert', 'addu $a0, $a0, $v0']
    rows = [('o', a, b) for a, b in zip(target, candidate)]
    asm = '\n'.join(target)
    (family, text), = repair.measured_variants(source, 'f', asm, rows)
    assert family == 'target_call_arity'
    assert 'convert(*p)' in text and 'convert(s32)' in text
    assert not repair.measured_variants(source, 'f', asm, [(' ', x, x) for x in target])
    assert not repair.measured_variants(source.replace('0x1000040', 'side_effect()'), 'f', asm, rows)
    assert not repair.measured_variants(source, 'f', asm, [('o', a, b.replace('convert', 'other'))
                                                        for a, b in zip(target, candidate)])
