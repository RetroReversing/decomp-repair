"""A run of reads of a global pointer, through the local that holds it."""
from decomprepair import global_pointer_run_repairs as r

SOURCE = '''void f(void)
{
  void *n;
  u32 g;
  s32 e;
  if (D_1 != 0)
  {
    n = D_800EDA8C;
    while (n != 0)
    {
      h(n);
      n = D_800EDA8C;
    }
    g = (*((u16 *) (((char *) D_800EDA8C) + 0xFC2))) * 3;
    e = *((s32 *) (((char *) D_800EDA8C) + 0xF68));
    *((s32 *) (((char *) D_800EDA8C) + 0x118)) = (g >> 7) & 0xFFFF;
    if (e != 0)
    {
      *((s32 *) (((char *) D_800EDA8C) + 0xF74)) += g;
    }
    k();
    *((s32 *) (((char *) D_800EDA8C) + 0x11C)) = 1;
  }
}
'''


def test_the_block_after_the_loop_uses_the_local():
    # A MIPS function with this block: its pointer was one register off; through the loop's local, 535 -> 480.
    (family, out), = r.variants(SOURCE, 'f')
    assert family == 'global_pointer_run'
    assert '    n = D_800EDA8C; g = (*((u16 *) (((char *) n) + 0xFC2))) * 3;' in out
    assert 'e = *((s32 *) (((char *) n) + 0xF68));' in out
    assert '*((s32 *) (((char *) n) + 0xF74)) += g;' in out
    # the run ends at the call; what follows it is untouched
    assert '*((s32 *) (((char *) D_800EDA8C) + 0x11C)) = 1;' in out
    assert out.count('D_800EDA8C') == 4


def test_a_copy_right_before_the_run_is_not_repeated():
    source = SOURCE.replace('    g = (*', '    n = D_800EDA8C;\n    g = (*', 1)
    (_, out), = r.variants(source, 'f')
    assert out.count('n = D_800EDA8C;') == 3


def test_left_alone_otherwise():
    # no local copy, fewer than three reads, a write to the local in the run, a write to the global itself
    assert r.variants(SOURCE.replace('n = D_800EDA8C;', 'n = 0;'), 'f') == []
    assert r.variants(SOURCE.replace('    e = *((s32 *) (((char *) D_800EDA8C) + 0xF68));\n', '')
                      .replace('      *((s32 *) (((char *) D_800EDA8C) + 0xF74)) += g;\n', '')
                      .replace('    *((s32 *) (((char *) D_800EDA8C) + 0x118)) = (g >> 7) & 0xFFFF;\n', ''), 'f') == []
    assert r.variants(SOURCE.replace('    e = *', '    n = 0; e = *'), 'f') == []
    assert r.variants(SOURCE.replace('    e = *', '    D_800EDA8C = 0; e = *'), 'f') == []
