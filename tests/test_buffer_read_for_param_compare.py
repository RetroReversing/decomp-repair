"""A compare against a parameter turned into the read of the buffer the target loads from."""
from decomprepair import buffer_read_for_param_compare as r

SOURCE = '''void f(s32 arg0)
{
  char sp10[0x28];
  g(arg0 + 0x10, sp10);
  if (((unsigned char) arg0) == 1)
  {
    h(arg0, sp10);
  }
}
'''
ASM = '''jal g
addiu      $a1, $sp, 0x10
lh         $v1, 0x36($sp)
addiu      $v0, $zero, 1
'''


def test_the_compare_reads_the_buffer_at_the_loads_offset():
    [(family, text)] = r.variants(SOURCE, 'f', ASM)
    assert family == 'buffer_read_for_param_compare'
    assert 'if ((*(s16 *)(sp10 + 0x26)) == 1)' in text
    assert 'h(arg0, sp10);' in text


def test_nothing_outside_the_buffer_or_without_a_load():
    assert r.variants(SOURCE, 'f', ASM.replace('0x36', '0x40')) == []
    assert r.variants(SOURCE, 'f', ASM.replace('lh ', 'lwc1')) == []
    assert r.variants(SOURCE, 'f', '') == []
    assert r.variants(SOURCE.replace('arg0) == 1', 'x) == 1'), 'f', ASM) == []


def test_it_declares_itself():
    assert r.REPAIR['families'] == ('buffer_read_for_param_compare',)
