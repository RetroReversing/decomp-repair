"""ladder_result_narrow: a bit-test ladder's result as the `else if` chain, in a byte, in a function returning 32 bits.

Shape of an 89-instruction audio-setup function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 90 -> 0 with the three
edits together; the 64-bit return alone scored 180, the chain and the byte with the 64-bit return 100)."""
from decomprepair import ladder_result_narrow as ladder

SOURCE = '''s32 start(s32 *, s32, s32, s32);
extern s32 D_80100000;
unsigned long long setup(s32 *arg0, u16 arg1, u16 arg2, u32 arg3)
{
  s32 temp;
  s32 var_v0;
  D_80100000 = 1;
  temp = start(arg0, 0, 0, 0);
  var_v0 = 2;
  if (!(arg3 & 0x10000))
  {
    var_v0 = 3;
    if (!(arg3 & 0x20000))
    {
      var_v0 = 4;
      if (!(arg3 & 0x40000))
      {
        var_v0 = 0;
 do { if (!(arg3 & 0x80000)) { var_v0 = 1; } } while (0);
      }
    }
  }
  start(arg0, arg1 & 0xFFFF, arg2 & 0xFFFF, var_v0);
  return 0;
}
'''

CHAIN = '''  if (arg3 & 0x10000) var_v0 = 2;
  else if (arg3 & 0x20000) var_v0 = 3;
  else if (arg3 & 0x40000) var_v0 = 4;
  else if (arg3 & 0x80000) var_v0 = 0;
  else var_v0 = 1;
'''


def test_the_three_edits_are_one_child_first():
    out = ladder.variants(SOURCE, 'setup')
    first = out[0][1]
    assert out[0][0] == 'ladder_result_narrow'
    assert first.startswith('s32 start') and '\ns32 setup(' in first and 'unsigned long long' not in first
    assert '  u8 var_v0;' in first and CHAIN in first and 'while (0)' not in first
    assert 'start(arg0, arg1 & 0xFFFF, arg2 & 0xFFFF, var_v0);' in first


def test_the_pieces_follow_the_combination():
    texts = [text for _, text in ladder.variants(SOURCE, 'setup')]
    assert len(texts) == 4
    assert 'unsigned long long' in texts[1] and '  u8 var_v0;' in texts[1] and CHAIN in texts[1]
    assert '  s32 var_v0;' in texts[2] and CHAIN in texts[2] and 'unsigned long long' in texts[2]
    assert texts[3].count('s32 setup(') == 1 and 'while (0)' in texts[3] and 's32 var_v0;' in texts[3]


def test_a_narrow_return_or_other_reads_are_left_alone():
    narrow = SOURCE.replace('unsigned long long setup', 's32 setup')
    assert len(ladder.variants(narrow, 'setup')) == 2
    kept = SOURCE.replace('  return 0;', '  return var_v0;')
    assert ladder.variants(kept, 'setup') == []
    assert ladder.variants(SOURCE.replace('  var_v0 = 3;', '  var_v0 = temp;'), 'setup') == []
    assert ladder.variants(SOURCE.replace('(!(arg3 & 0x20000))', '(arg3 & 0x20000)'), 'setup') == []
