from decomprepair import shared_guard_call_switch as repair

HEADER = '''typedef unsigned char u8;
typedef signed int s32;
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
'''
ASM = '''beq $v1, $v0, .Lcall
slti $v0, $v1, 0x11
bnez $v0, .Lother
slti $v0, $v1, 0x2a
beqz $v0, .Lother
slti $v0, $v1, 0x28
'''
SOURCE = '''void f(void *p) {
    s32 arg;
    if ((M2C_FIELD(p, u8 *, 4) == 0x11) || (((s32) M2C_FIELD(p, u8 *, 4) >= 0x11) && ((s32) M2C_FIELD(p, u8 *, 4) < 0x2A) && ((s32) M2C_FIELD(p, u8 *, 4) >= 0x28))) {
        arg = 0x1A;
        goto shared;
    }
    arg = 0x19;
    if (condition(p)) {
shared:
        use(p, arg);
    }
    next(p);
}
'''


def test_restores_cases_and_the_original_guarded_default():
    out = repair.variants(SOURCE, 'f', ASM, HEADER)
    assert len(out) == 1
    text = out[0][1]
    assert 'switch (M2C_FIELD(p, u8 *, 4))' in text
    assert all(f'case {n}:' in text for n in ('0x11', '0x28', '0x29'))
    assert 'use(p, 0x1A);' in text and 'if (condition(p))' in text and 'use(p, 0x19);' in text
    assert 'goto shared' not in text and 's32 arg;' not in text and 'next(p);' in text


def test_rejects_unproved_or_unsafe_shapes():
    assert repair.variants(SOURCE, 'f', ASM.replace('0x2a', '0x2b'), HEADER) == []
    assert repair.variants(SOURCE, 'f', '', HEADER) == []
    assert repair.variants(SOURCE.replace('next(p);', 'next(arg);'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE.replace('void *p', 'volatile void *p'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE, 'f', ASM, HEADER.replace('unsigned char u8', 'volatile unsigned char u8')) == []
    assert repair.variants(SOURCE, 'f', ASM, HEADER + '#define p changed()\n') == []
    assert repair.variants(SOURCE, 'f', ASM, HEADER + '#define condition(p) arg\n') == []
    assert repair.variants(SOURCE, 'f', ASM, HEADER + '#define use(a,b) arg\n') == []
    assert repair.variants(SOURCE.replace('0x11', '017'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE.replace('goto shared;', 'goto shared; /* keep */'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE.replace('    next(p);', '    goto shared;\n    next(p);'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE.replace('    next(p);', '    else { next(p); }\n    next(p);'), 'f', ASM, HEADER) == []


def test_grouping_and_ranges_must_match_the_same_boolean_function():
    assert repair.variants(SOURCE.replace('|| (((s32)', '|| (((s32)', 1).replace('>= 0x28', '>= 0x30'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE.replace(' < 0x2A', ' < 0xFF'), 'f', ASM, HEADER) == []
    assert repair.variants(SOURCE.replace('M2C_FIELD(p, u8 *, 4) < 0x2A', 'M2C_FIELD(p, u8 *, 5) < 0x2A'), 'f', ASM, HEADER) == []


def test_all_byte_values_choose_the_same_call_arm():
    import re

    text = repair.variants(SOURCE, 'f', ASM, HEADER)[0][1]
    cases = {int(value, 0) for value in re.findall(r'\bcase\s+(0x[0-9a-f]+|\d+)\s*:', text)}
    for value in range(256):
        original = value == 0x11 or (value >= 0x11 and value < 0x2A and value >= 0x28)
        assert original == (value in cases)
