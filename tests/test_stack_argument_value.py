"""A call's stack arguments m2c left in `spNN` locals are passed in the call."""
from decomprepair import registry
from decomprepair import stack_argument_value as s

SOURCE = '''M2C_UNK g(s32, void *, f32, f32);       /* extern */

void f(s32 i, f32 *p) {
    f32 sp10;

    if (i == 2) {
        sp10 = 0.0f;
        g(i, p, sp10, 0.001f);
    } else {
        sp10 = -p[2] * 0.2f;
        g(i, p, -p[0] * 0.2f, -p[1] * 0.15f);
    }
}
'''
ASM = '''sw         $zero, 0x10($sp)
lw         $a2, 0x10($sp)
jal        g
addu       $a1, $s1, $zero
beqz       $v0, .L1
nop
swc1       $fv0, 0x10($sp)
mfc1       $a2, $ft1
jal        g
addu       $a1, $s1, $zero
'''


def test_the_stored_words_are_passed_and_the_prototype_widened():
    [(family, out)] = s.variants(SOURCE, 'f', ASM)
    assert family == 'stack_argument_value'
    assert 'g(s32, void *, f32, f32, f32);' in out
    assert 'g(i, p, 0.0f, 0.001f, 0.0f);' in out
    assert 'g(i, p, -p[0] * 0.2f, -p[1] * 0.15f, -p[2] * 0.2f);' in out
    assert 'sp10' not in out


def test_declines_without_the_stores_or_with_other_uses():
    assert s.variants(SOURCE, 'f', ASM.replace('0x10($sp)', '0x20($sp)')) == []
    assert s.variants(SOURCE, 'f', '') == []
    assert s.variants(SOURCE.replace('} else {', '    h(&sp10);\n    } else {'), 'f', ASM) == []


def test_declared_to_the_registry():
    assert any(r.module == 'stack_argument_value' for r in registry.declared())
