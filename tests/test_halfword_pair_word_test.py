"""A halfword compared with zero, read as the word the target reads."""
from decomprepair.halfword_pair_word_test import variants

CODE = '''void f(char *p)
{
  if (((s32) (*((s16 *) (p + 0x178)))) == 0)
  {
    g(p);
  }
  if ((*((u16 *) (p + 0x17A))) == 3)
  {
    h(p);
  }
}
'''
ASM = 'lw         $v0, 0x178($s2)\nbnez       $v0, .L80068B58\n'


def test_a_halfword_the_target_reads_as_a_word_is_read_as_one():
    [(family, child)] = variants(CODE, 'f', 'mips', ASM)
    assert family == 'halfword_pair_word_test'
    assert '((s32) (*((s32 *) (p + 0x178)))) == 0' in child
    assert '*((u16 *) (p + 0x17A))' in child


def test_nothing_is_offered_without_a_word_load_at_that_offset():
    assert variants(CODE, 'f', 'mips', 'lh $v0, 0x178($s2)\n') == []
    assert variants(CODE, 'f', 'mips', 'lw $v0, 0x17A($s2)\n') == []  # that read is compared with 3, not zero
    assert variants(CODE, 'f', 'mips', '') == []


def test_other_processors_are_not_offered_it():
    assert variants(CODE, 'f', 'ppc', ASM) == []
