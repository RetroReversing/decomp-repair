from decomprepair import registry
from decomprepair.symbol_low_half_offset import FAMILY, REPAIR, variants

SOURCE = """extern s32 D_80075D54;

void f(void) {
    if (M2C_FIELD(&D_80075D54, s32 *, 0) != 0) {
        g();
        return;
    }
    M2C_FIELD(&D_80075D54, s32 *, 0x5D54) = 1;
}
"""
ASM = """    lui $v1, %hi(D_80075D54)
    lw $v0, %lo(D_80075D54)($v1)
    sw $a0, 0x5D54($v1)
"""


def _children(source=SOURCE, asm=ASM):
    return [text for family, text in variants(source, 'f', asm) if family == FAMILY]


def test_the_duplicated_low_half_becomes_offset_zero():
    assert _children() == [SOURCE.replace('0x5D54) = 1', '0) = 1')]
    assert _children(asm='') == _children()


def test_a_cast_spelling_a_negative_immediate_and_one_child_per_site():
    source = ('void f(void) {\n    *(s32 *)((s8 *)&D_8007D554 + -0x2AAC) = 1;\n'
              '    M2C_FIELD(&D_8007D554, u8 *, 0xD554) = 2;\n}\n')
    asm = 'lui $v1, %hi(D_8007D554)\nsw $a0, -0x2AAC($v1)\n'
    kids = _children(source, asm)
    assert len(kids) == 3
    assert '&D_8007D554 + 0)' in kids[0] and 'u8 *, 0)' in kids[0]
    assert 'u8 *, 0xD554)' in kids[1] and '&D_8007D554 + -0x2AAC)' in kids[2]


def test_other_offsets_and_unconfirmed_assembly_are_left_alone():
    assert not _children(SOURCE.replace('0x5D54', '0x5D50'), '')
    assert not _children(asm='lui $v1, %hi(D_80075D54)\nsw $a0, %lo(D_80075D54)($v1)\n')
    assert not _children(SOURCE.replace('D_80075D54', 'gState'), '')


def test_it_declares_itself():
    assert REPAIR['families'] == (FAMILY,)
    assert any(entry.module == 'symbol_low_half_offset' for entry in registry.declared())
