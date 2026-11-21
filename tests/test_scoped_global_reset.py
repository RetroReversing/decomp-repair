from decomprepair.scoped_global_reset import FAMILY, variants

SOURCE = '''extern s8 a;
extern s8 b;
extern u8 c;
extern s32 flag;
extern s32 count;
void f(void) {
    if (ready != 0) {
        a = 0; b = 0; c = 0;
        { s32 x = old_x; s32 y = old_y; new_x = x; new_y = y; }
        flag = 0;
        i = 0;
        if (count > 0) { scan(); }
    }
}'''
ASM = '''sb $zero, %lo(a)($at)
sb $zero, %lo(b)($at)
sb $zero, %lo(old_c)($at)
lw $v0, %lo(old_x)($v0)
lw $v1, %lo(old_y)($v1)
sw $v0, %lo(new_x)($at)
sw $v1, %lo(new_y)($at)
lw $v0, %lo(old_count)($v0)
sw $zero, %lo(flag)($at)
'''


def test_offers_the_combination_and_the_scope_only_variant():
    [(first_family, combined), (second_family, scoped)] = variants(SOURCE, 'f', 'mips', ASM)
    assert first_family == second_family == FAMILY
    assert scoped == SOURCE.replace('a = 0;', 'do { a = 0; } while (0);')
    assert combined == scoped.replace('extern u8 c;', 'extern volatile u8 c;').replace(
        'extern s32 flag;', 'extern volatile s32 flag;').replace('extern s32 count;', 'extern volatile s32 count;')


def test_requires_target_reset_order_and_checked_declarations():
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('sb $zero, %lo(b)', 'sb $v0, %lo(b)'))
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('%lo(old_x)', '%lo(other)'))
    assert not variants(SOURCE.replace('extern u8 c;', 'extern u16 c;'), 'f', 'mips', ASM)
