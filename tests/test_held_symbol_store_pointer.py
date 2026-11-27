"""Two stores through one held symbol address (an N64 menu routine, -O1: 1015 -> 25)."""
from decomprepair.held_symbol_store_pointer import FAMILY, REPAIR, variants

ASM = """
/* 00 */  jal        func_80000000
/* 04 */  addiu      $a1, $zero, 0x3A
/* 08 */  lui        $v0, %hi(D_80100020)
/* 0C */  addiu      $v0, $v0, %lo(D_80100020)
/* 10 */  sb         $zero, 0x0($v0)
/* 14 */  addiu      $v1, $zero, 0x10
/* 18 */  sh         $v1, -0x16($v0)
"""

SOURCE = """extern u8 D_80100020;
void menu(s32 input)
{
    if (input & 0x20) {
        D_80100020 = 0;
        *(s16 *) (&D_80100020 - 0x16) = 0x10;
    }
    if (input & 1) {
        D_80100020 = 0;
        D_8010000A = 0xF0;
    }
}
"""


def test_all_pairs_together_then_each():
    found = variants(SOURCE, 'menu', asm=ASM)
    assert [family for family, _ in found] == [FAMILY] * 3
    both = found[0][1]
    assert ('{ u8 *p; do { p = (u8 *) &D_80100020; } while (0); *(u8 *) p = 0; '
            '*(s16 *) (p - 0x16) = 0x10; }') in both
    assert '*(s16 *) (p - 0x16) = 0xF0; }' in both


def test_the_spelled_out_cast_form_and_no_held_address():
    spelled = SOURCE.replace('*(s16 *) (&D_80100020 - 0x16)', '*((s16 *) (((u8 *) (&D_80100020)) - 0x16))')
    assert variants(spelled, 'menu', asm=ASM)[0][1].count('do { p =') == 2
    assert variants(SOURCE, 'menu', asm='sb $zero, %lo(D_80100020)($at)\n') == []
    assert REPAIR['families'] == (FAMILY,)
