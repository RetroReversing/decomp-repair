"""A word global cast to a halfword, read as the halfword the target loads at the symbol's own address.

Synthetic shape of a sound-sequence interpreter's command reads (KMC GCC 2.7.2); on the 1315-instruction interpreter
the seven reads were 16130 -> 14715 together (exact judge, decompdecomp's tests)."""
from decomprepair import registry
from decomprepair import word_global_narrow_read as m

SOURCE = '''typedef unsigned char u8;
typedef unsigned short u16;
typedef short s16;
typedef unsigned int u32;
extern u32 gCmd;
extern u32 gOther;

void op(u8 *voice)
{
  voice[0xC0] = (u8) (u16) gCmd;
  voice[0x6A] = (s16) gCmd >> 1;
  voice[0x6B] = (u16) gOther;
  voice[0x6C] = (u8) gCmd;
}
'''
ASM = '''lui $v0, %hi(gCmd)
lhu $v0, %lo(gCmd)($v0)
lh $v1, %lo(gCmd)($v1)
lhu $a0, %lo(gOther + 0x2)($a0)
'''


def texts(source=SOURCE, asm=ASM):
    found = m.variants(source, 'op', asm)
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_every_halfword_cast_at_once_then_each_alone():
    together, first, second = texts()
    assert 'voice[0xC0] = (u8) (*((u16 *) (&gCmd)));' in together
    assert 'voice[0x6A] = (*((s16 *) (&gCmd))) >> 1;' in together
    # a load at another offset says nothing about the symbol's own address; no byte load: the byte cast stays
    assert 'voice[0x6B] = (u16) gOther;' in together and 'voice[0x6C] = (u8) gCmd;' in together
    assert 'voice[0xC0] = (u8) (*((u16 *) (&gCmd)));' in first and '(s16) gCmd' in first
    assert '(u16) gCmd' in second and '(*((s16 *) (&gCmd)))' in second


def test_nothing_without_a_narrow_load_or_for_a_halfword_global():
    assert texts(asm='lw $v0, %lo(gCmd)($v0)\n') == []
    assert texts(SOURCE.replace('extern u32 gCmd;', 'extern u16 gCmd;')) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'word_global_narrow_read')
    assert registry.problems(repair) == []
