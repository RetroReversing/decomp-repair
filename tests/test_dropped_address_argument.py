"""The symbol address a call passed that m2c dropped, written back from the target's assembly."""
from decomprepair.dropped_address_argument import FAMILY, variants

SOURCE = """void wrap(s32); /* matched callee */
extern s32 gSlots;

void load(void) {
    wrap(M2C_FIELD(&gSlots, s32 *, 0x10));
    wrap(M2C_FIELD(&gSlots, s32 *, 0x20));
    wrap(M2C_FIELD(&gSlots, s32 *, 0x20));
}
"""

ASM = """glabel load
  lui $s0, %hi(D_C)
  addiu $s0, $s0, %lo(D_C)
  lui $a1, %hi(D_A)
  lw $a0, 0x10($s1)
  jal wrap
  addiu $a1, $a1, %lo(D_A)
  lw $a0, 0x20($s1)
  jal wrap
  addu $a1, $s0, $zero
  lw $a0, 0x20($s1)
  jal wrap
  addu $a1, $s0, $zero
"""


def test_each_call_gets_its_address_back():
    ((family, text),) = variants(SOURCE, 'load', asm=ASM, arch='mips')
    assert family == FAMILY
    assert 'wrap(M2C_FIELD(&gSlots, s32 *, 0x10), D_A);' in text
    assert text.count('wrap(M2C_FIELD(&gSlots, s32 *, 0x20), D_C);') == 2
    assert 'void wrap(); /* matched callee */' in text
    assert 'extern u8 D_A[];' in text and 'extern u8 D_C[];' in text


def test_a_call_count_that_differs_or_no_address_offers_nothing():
    assert variants(SOURCE.replace('    wrap(M2C_FIELD(&gSlots, s32 *, 0x10));\n', ''), 'load', asm=ASM) == []
    assert variants(SOURCE, 'load', asm='glabel load\n  jal wrap\n  nop\n' * 3) == []
