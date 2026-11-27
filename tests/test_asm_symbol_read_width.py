"""Table reads at the width the target loads them with (a 1300-instruction routine, 10695 -> 9925)."""
from decomprepair.asm_symbol_read_width import FAMILY, FAMILY_CAST, REPAIR, variants

SOURCE = """inline static s8 __repair_inline(s8 a)
{
  return a;
}

void pick(s32 i, f32 x)
{
  s8 d;
  d = __repair_inline(*((u16 *) (D_800C46A0 + (i * 0xE8))));
  link(*((u16 *) (D_80109688 + (i * 4))));
  if (x >= (-((int) 0.0002f)))
  {
    use(d, *((u16 *) (D_800C4738 + i)));
  }
}
"""

ASM = """
    lb         $v1, %lo(D_800C46A0)($v1)
    lw         $a1, %lo(D_80109688)($a1)
    lhu        $a1, %lo(D_800C4738)($a1)
    lw         $a1, %lo(D_80109688)($a1)
"""


def test_every_symbol_together_first_then_each():
    found = variants(SOURCE, 'pick', asm=ASM)
    assert [family for family, _ in found] == [FAMILY, FAMILY, FAMILY, FAMILY_CAST]
    both = found[0][1]
    assert 'd = *((s8 *) (D_800C46A0 + (i * 0xE8)));' in both
    assert 'link(*((s32 *) (D_80109688 + (i * 4))));' in both
    assert '*((u16 *) (D_800C4738 + i))' in both
    assert 'if (x >= (-(0.0002f)))' in found[3][1]


def test_a_symbol_loaded_two_ways_is_left_alone():
    asm = ASM + '    lhu        $a1, %lo(D_80109688)($a1)\n'
    found = variants(SOURCE, 'pick', asm=asm)
    assert all('*((s32 *) (D_80109688' not in text for _, text in found)


def test_no_assembly_no_width_children():
    assert [family for family, _ in variants(SOURCE, 'pick')] == [FAMILY_CAST]


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and 'asm' in REPAIR['needs']


def test_a_record_member_is_read_at_the_targets_width_and_converted_to_float():
    source = ('void f(void)\n{\n  a = *((M2C_UNK *)((s8 *)&D_800DB1B8 + 0x210A + o));\n'
              '  b = *(f32 *)((M2C_UNK *)((s8 *)&D_800DB1B8 + 0x2114 + o)) / 2.0f;\n}\n')
    asm = 'lh $s2, %lo(D_800DB1B8 + 0x210A)($s2)\nlh $v1, %lo(D_800DB1B8 + 0x2114)($v1)\n'
    children = variants(source, 'f', asm)
    family, child = children[0]
    assert family == 'asm_offset_read_width'
    assert '*((s16 *)((s8 *)&D_800DB1B8 + 0x210A + o))' in child
    assert '(f32) *(s16 *)((M2C_UNK *)((s8 *)&D_800DB1B8 + 0x2114 + o)) / 2.0f' in child
    assert len(children) == 3
