"""loop_copy_address_stage: a copy loop's source address named part by part inside the loop.

Synthetic shape of a 61-instruction KMC `-O1` record copy: the pointer set before the loop compiled one register round
from the target; the staged body was exact."""
from decomprepair import loop_copy_address_stage as s

SOURCE = '''extern char gTable[];
extern u16 gText[];
void pick(u16 id, s32 player) {
  s32 i;
  u16 *src;
  src = (u16 *) (((gTable + 0x64) + (player * 0x178)) + ((id & 0xFF) * 0x12));
  for (i = 0; i < 8; i++)
  {
    do
    {
      gText[(unsigned short) i] = src[i];
    }
    while (0);
  }
  done();
}
'''


def _texts(source=SOURCE, header=''):
    return [text for family, text in s.variants(source, 'pick', header=header) if family == s.FAMILY]


def test_the_parts_are_staged_in_the_loop_with_either_term_first():
    texts = _texts()
    assert len(texts) == 2
    one = next(t for t in texts if 'stage_first = player * 0x178;' in t)
    assert 'src = (u16 *)' not in one
    assert ('  {\n    u16 *stage_dst = &gText[i];\n    int stage_first = player * 0x178;\n'
            '    int stage_second = id & 0xFF;\n    char *stage_base = (char *) gTable + 0x64;\n'
            '    *stage_dst = ((u16 *) (stage_second * 0x12 + (stage_first + (int) stage_base)))[i];\n  }') in one


def test_the_first_term_keeps_its_grouping():
    other = next(t for t in _texts() if 'stage_second = player;' in t)
    assert 'int stage_first = (id & 0xFF) * 0x12;' in other


def test_a_pointer_read_after_the_loop_is_left_alone():
    assert _texts(SOURCE.replace('done();', 'done(src);')) == []


def test_a_pointer_assigned_again_is_fine():
    assert len(_texts(SOURCE.replace('done();', 'src = 0;'))) == 2


def test_a_global_index_or_a_wider_table_is_left_alone():
    assert _texts(SOURCE.replace('player * 0x178', 'gCount * 0x178')) == []
    assert _texts(SOURCE.replace('extern char gTable[];', 'extern u16 gTable[];')) == []


def test_a_loop_that_does_more_is_left_alone():
    assert _texts(SOURCE.replace('gText[(unsigned short) i] = src[i];', 'gText[i] = src[i]; mark(i);')) == []
