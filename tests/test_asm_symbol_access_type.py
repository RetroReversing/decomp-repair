"""Stores and float reads of a symbol written at the type the target accesses it with."""
from decomprepair.asm_symbol_access_type import FAMILY, REPAIR, variants

SOURCE = """void spin(s32 o, f32 x)
{
  *(s32 *)((u8 *)&D_80100028 + o) = x * 0.5f;
  *(s32 *)((u8 *)&D_801000FD + o) = 2;
  use(*(s32 *)((u8 *)&D_80100010 + o) + x);
  use(*(s32 *)((u8 *)&D_80100040 + o));
}
"""

ASM = """
    swc1       $f0, %lo(D_80100028)($at)
    sb         $v1, %lo(D_801000FD)($at)
    lwc1       $f0, %lo(D_80100010)($at)
    lw         $v0, %lo(D_80100040)($v0)
"""


def test_all_together_first_then_each():
    found = variants(SOURCE, 'spin', asm=ASM)
    assert [family for family, _ in found] == [FAMILY] * 4
    together = found[0][1]
    assert '*(f32 *)((u8 *)&D_80100028 + o) = x * 0.5f;' in together
    assert '*(u8 *)((u8 *)&D_801000FD + o) = 2;' in together
    assert '*(f32 *)((u8 *)&D_80100010 + o) + x' in together
    assert '*(s32 *)((u8 *)&D_80100040 + o)' in together  # a word stays a word


def test_a_symbol_accessed_two_ways_is_left_alone():
    assert variants(SOURCE, 'spin', asm='sw $v0, %lo(D_80100028)($at)\nswc1 $f0, %lo(D_80100028)($at)\n') == []


def test_nothing_without_the_target():
    assert variants(SOURCE, 'spin') == []
    assert REPAIR['needs'] == ('source', 'name', 'asm')


BYTES = """extern char D_80100200[];
extern u8 D_80100204[];
void reset(s32 o)
{
  D_80100200[o] = 0;
  D_80100204[o] = 0;
  use(&D_80100200[o], D_80100200[o + 4]);
}
"""


def test_a_byte_array_element_the_target_stores_as_a_word():
    asm = 'sw $zero, %lo(D_80100200)($at)\nsb $zero, %lo(D_80100204)($at)\n'
    [(family, child)] = variants(BYTES, 'reset', asm=asm)
    assert family == FAMILY
    assert '*(s32 *)&D_80100200[o] = 0;' in child
    assert 'D_80100204[o] = 0;' in child and '*(u8 *)&D_80100204' not in child
    assert 'use(&D_80100200[o], *(s32 *)&D_80100200[o + 4]);' in child
    assert 'extern char D_80100200[];' in child
