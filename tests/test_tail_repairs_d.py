"""Round-six repairs: calls in the target's order, a 16.16 sign as a halfword, value_repairs' pointer split cleaned."""
from decomprepair import debris, halfword_sign_repairs, target_call_order_repairs

CALLS = '''s32 g();
void f(void *arg0, s32 arg1, s32 arg3) {
    void *temp_v1;
    void *temp_s0;

    temp_v1 = (*(void **)((char *)(arg0) + 0x68));
    temp_s0 = (char *)(temp_v1) + 0x14;
    g((*(s32 *)((char *)(temp_s0) + 0x44)), arg1, arg3, (*(s32 *)((char *)(temp_v1) + 0x14)) & 1);
    g((*(s32 *)((char *)(temp_s0) + 0x40)), arg1, (*(s32 *)((char *)(temp_v1) + 0x14)) & 1);
    h(arg0);
}
'''
ASM = '''lw         $a0, 0x40($s0)
jal        g
lw         $a0, 0x44($s0)
jal        g
'''


def test_calls_take_the_targets_order_and_the_derived_pointer():
    # An N64 function: 720 points off with the calls swapped, 150 in the target's order through the derived pointer.
    (family, ordered), (_, derived) = target_call_order_repairs.variants(CALLS, 'f', ASM)
    assert family == 'target_call_order'
    assert ordered.index('+ 0x40)), arg1, (*') < ordered.index('+ 0x44)), arg1, arg3')
    assert 'g((*(s32 *)((char *)(temp_s0) + 0x40)), arg1, (*(s32 *)((char *)(temp_s0) + 0)) & 1);' in derived
    assert '(char *)(temp_v1) + 0x14)) & 1' not in derived


def test_calls_left_alone_in_order_or_unknown():
    swapped = CALLS.replace('+ 0x44)), arg1, arg3', '+ 0x4X').replace('+ 0x40)), arg1, (*', '+ 0x44)), arg1, (*') \
        .replace('+ 0x4X', '+ 0x40)), arg1, arg3')
    assert target_call_order_repairs.variants(swapped, 'f', ASM) == []  # already the target's order
    assert target_call_order_repairs.variants(CALLS, 'f', ASM.replace('0x44', '0x48')) == []
    assert target_call_order_repairs.variants(CALLS, 'f', '') == []


SIGN = '''s32 f(u8 fl) {
    s32 v;

    if (!(fl & 4)) {
        return 0;
    }
    v = (((fl & 0x20) != 0) * -0x10000) | 0x10000;
    return v;
}
'''


def test_the_sign_is_a_halfword():
    # Twin N64 functions: 1575 points off as m2c wrote it, 1260 with the sign as an s16 (the game's sll 16).
    (family, out), = halfword_sign_repairs.variants(SIGN, 'f')
    assert family == 'halfword_sign'
    assert 's16 __repair_sign;' in out
    assert '    __repair_sign = -((fl & 0x20) != 0);\n    v = (__repair_sign << 16) | 0x10000;' in out
    assert halfword_sign_repairs.variants(SIGN.replace('-0x10000) | 0x10000', '-0x20000) | 0x20000'), 'f') == []


def test_the_pointer_split_is_one_sum_again():
    source = 'void f(void *b) {\n    char *q;\n\n    q = (char *)(b); q += (s32)(0x14);\n    g(q);\n}\n'
    assert 'q = (char *)(b) + 0x14;\n' in debris.clean(source)


def test_a_read_before_the_first_assignment_is_swapped_back():
    # An N64 function's best read `p` one line before setting it (a random statement swap); swapped back, and with the
    # values computed before the stores, it was exact.
    source = ('void f(void *a) {\n    void *p;\n    f32 t;\n    f32 u;\n\n'
              '    t = *(f32 *)((char *)(p) + 0x7C);\n    p = D[g(a)];\n    u = *(f32 *)((char *)(p) + 0x78);\n'
              '    h(t, u);\n}\n')
    out = debris.clean(source)
    assert '    p = D[g(a)];\n    t = *(f32 *)((char *)(p) + 0x7C);\n' in out
    fine = source.replace('    t = *(f32 *)((char *)(p) + 0x7C);\n    p = D[g(a)];\n',
                          '    p = D[g(a)];\n    t = *(f32 *)((char *)(p) + 0x7C);\n')
    assert debris.clean(fine) is None


def test_left_alone_when_a_call_may_set_it_through_an_address():
    source = ('void f(void) {\n    f32 sp38;\n    f32 sp40;\n    f32 t;\n\n    g(&sp38);\n'
              '    t = sp40 + 1.0f;\n    sp40 = t;\n    h(t);\n}\n')
    assert debris.clean(source) is None
