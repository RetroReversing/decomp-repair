from decomprepair import remask_volatile

ASM = '''
lui        $v0, %hi(D_80100010)
lhu        $v0, %lo(D_80100010)($v0)
andi       $v0, $v0, 0xFFFF
addiu      $v1, $zero, 0x5
'''

SOURCE = '''extern u16 D_80100010;
void f(void)
{
    if (D_80100010 != 5) {
        g();
    }
}
'''


def test_a_masked_narrow_load_makes_the_global_volatile():
    assert remask_volatile.variants(SOURCE, 'f', ASM) == [
        ('remask_volatile', SOURCE.replace('extern u16', 'extern volatile u16'))]


def test_no_mask_no_child():
    assert remask_volatile.variants(SOURCE, 'f', ASM.replace('0xFFFF', '0xF')) == []
    assert remask_volatile.variants(SOURCE.replace('extern u16', 'extern volatile u16'), 'f', ASM) == []
