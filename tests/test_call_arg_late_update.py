"""A staged call argument written in the call, with the counter updates after it.

Synthetic shape of one loop of a mixing function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`). The exact-judge
replay is in decompdecomp's tests (it needs the compiler): two such loops 1560 -> 1150 (one alone 1355), 1680 -> 1330 on
the saved best."""
from decomprepair import call_arg_late_update as m
from decomprepair import registry

SOURCE = '''typedef unsigned short u16;
typedef int s32;
inline static u16 cut(unsigned arg0)
{
  return (u16) arg0;
}
inline static int bump(void)
{
  return (--g_count) == 0;
}
extern s32 g_count;
void mix(s32 *table, u16 index)
{
  s32 temp;
  s32 step;
  s32 count;
  step = 0;
  count = 0;
  do
  {
    temp = cut(step);
    step += 0xC0;
    ++count;
    emit(table[index], temp);
  }
  while (count < 4);
  temp = cut(step);
  step += 0xC0;
  emit(table[index], temp);
  temp = bump();
  count += 1;
  emit(table[index], temp);
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'mix')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_call_takes_the_expression_and_the_updates_follow_it():
    both = texts()[0]
    assert '    emit(table[index], cut(step));\n    step += 0xC0;\n    ++count;\n' in both
    assert 'temp = cut(step);' not in both


def test_a_side_effecting_helper_is_not_moved():
    for text in texts():
        assert 'temp = bump();' in text


def test_updates_the_call_reads_stop_the_move():
    reads = SOURCE.replace('emit(table[index], temp);\n  }\n  while', 'emit(table[count], temp);\n  }\n  while')
    for text in texts(reads):
        assert 'temp = cut(step);\n    step += 0xC0;\n    ++count;' in text or text.count('emit(table[count], cut(step))') == 0


def test_a_staged_local_read_later_is_kept():
    kept = SOURCE.replace('  emit(table[index], temp);\n  temp = bump();', '  emit(table[index], temp);\n  count = temp;\n  temp = bump();')
    assert all('emit(table[index], cut(step));\n  step += 0xC0;\n  count = temp' not in t for t in texts(kept))


def test_it_declares_itself_to_the_registry():
    assert any(r.module == 'call_arg_late_update' for r in registry.declared())


STRIPS = '''typedef int s32;
void draw(s32, s32, s32, s32, s32);
void strips(s32 h, s32 w, s32 step, s32 x0, s32 x1)
{
  s32 rows;
  s32 y;
  s32 y0;
  y = -x1;
  while (h > 0)
  {
    rows = h;
    if (w * h > 0x400)
    {
      rows = 0x400 / w;
    }
    y0 = y;
    y += step * rows;
    draw(x0, y0, x1, y, rows << 6);
    h -= rows;
  }
}
'''


def test_an_update_the_call_reads_moves_with_its_new_value_in_the_arguments():
    # a textured-strip drawer (SN64 GCC 2.8.1): the staged old value and the update before the call, 746 -> 126
    found = [t for _, t in m.variants(STRIPS, 'strips')]
    assert '    draw(x0, y, x1, y + step * rows, rows << 6);\n    y += step * rows;\n    h -= rows;' in found[0]
    assert 'y0 = y;' not in found[0]


def test_a_new_value_is_parenthesised_inside_a_larger_argument_and_steps_count():
    source = STRIPS.replace('draw(x0, y0, x1, y, rows << 6);', 'draw(x0, y0, x1, y * 2, rows << 6);')
    assert 'draw(x0, y, x1, (y + step * rows) * 2, rows << 6);' in m.variants(source, 'strips')[0][1]
    stepped = STRIPS.replace('y += step * rows;', '++y;')
    assert 'draw(x0, y, x1, y + 1, rows << 6);\n    ++y;' in m.variants(stepped, 'strips')[0][1]
    shifted = STRIPS.replace('y += step * rows;', 'y <<= rows - 1;')
    assert 'draw(x0, y, x1, (y << (rows - 1)), rows << 6);' in m.variants(shifted, 'strips')[0][1]


def test_an_update_read_by_the_call_that_reads_another_update_is_kept():
    # the new value would read `rows` after its own update moved: no child
    source = STRIPS.replace('    y0 = y;\n    y += step * rows;\n',
                            '    y0 = y;\n    rows += 1;\n    y += step * rows;\n')
    assert m.variants(source, 'strips') == []
    twice = STRIPS.replace('    y += step * rows;\n', '    y += step * rows;\n    y += 1;\n')
    assert m.variants(twice, 'strips') == []
