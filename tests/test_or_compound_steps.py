"""A word built with one `|` of two shifts written as an assignment and a compound `|=`."""
from decomprepair.or_compound_steps import FAMILY, variants

# A sound-sequence interpreter's voice scan (KMC GCC 2.7.2, N64): the key the loop compares.
SCAN = '''void f(u8 *v, u16 *cmd)
{
  u32 key = ((v[0x4E] + v[1]) << 8) | (cmd[0] << 16);
  u32 i;
  for (i = 0; i < n; i++)
  {
    test(key | i);
  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_a_declarations_word_is_built_in_steps_after_the_declarations():
    kids = _children(SCAN)
    assert kids[0] == SCAN.replace('  u32 key = ((v[0x4E] + v[1]) << 8) | (cmd[0] << 16);\n  u32 i;\n',
                                   '  u32 key;\n  u32 i;\n  key = ((v[0x4E] + v[1]) << 8);\n  key |= (cmd[0] << 16);\n')
    assert len(kids) == 2 and 'key = (cmd[0] << 16);\n  key |= ((v[0x4E] + v[1]) << 8);' in kids[1]


def test_a_statement_is_split_in_place():
    text = SCAN.replace('  u32 key = ', '  u32 key;\n  key = ', 1).replace('  u32 i;\n', '').replace('  u32 key;\n', '  u32 key;\n  u32 i;\n')
    kids = _children(text)
    assert kids and 'key = ((v[0x4E] + v[1]) << 8);\n  key |= (cmd[0] << 16);' in kids[0]


def test_an_or_of_plain_values_is_left_alone():
    assert _children(SCAN.replace('(cmd[0] << 16)', 'cmd[0]')) == []


def test_a_word_read_in_its_own_operands_is_left_alone():
    assert _children(SCAN.replace('(cmd[0] << 16)', '(key << 16)')) == []
