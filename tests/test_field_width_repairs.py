"""A field's or a global's type from the target's own loads and stores."""
from decomprepair import field_width_repairs as w

SOURCE = '''extern s8 D_80102EE8;

void f(void *arg0) {
    if (D_80102EE8 != 0) {
        g(M2C_FIELD(arg0, s32 *, 0x2C));
    }
}
'''
ASM = '''lui        $v0, %hi(D_80102EE8)
lbu        $v0, %lo(D_80102EE8)($v0)
lhu        $a0, 0x2C($a0)
'''


def test_types_from_the_targets_accesses():
    (family, both), (_, field), (_, symbol) = w.variants(SOURCE, 'f', ASM)
    assert family == 'field_width'
    assert 'M2C_FIELD(arg0, u16 *, 0x2C)' in both and '(*(u8 *)&D_80102EE8) != 0' in both
    assert 'M2C_FIELD(arg0, u16 *, 0x2C)' in field and 'if (D_80102EE8 != 0)' in field
    assert '(*(u8 *)&D_80102EE8)' in symbol and 's32 *, 0x2C' in symbol
    assert 'extern s8 D_80102EE8;' in both  # (the header declares it too: retyped where it's used)


def test_left_alone_when_the_target_disagrees_with_itself_or_agrees():
    assert w.variants(SOURCE, 'f', ASM + 'lw         $a1, 0x2C($a2)\nlb         $v1, %lo(D_80102EE8)($v1)\n') == []
    assert w.variants(SOURCE.replace('s8 D_', 'u8 D_').replace('s32 *, 0x2C', 'u16 *, 0x2C'), 'f', ASM) == []
