"""One list cursor walked by several loops, given a local per loop."""
from decomprepair import registry
from decomprepair.sequential_cursor_split import FAMILY, variants

SOURCE = '''void walk(void *a, void *b)
{
  void *cur;
  void *var_a1_2;
  var_a1_2 = a;
  cur = *((void **) a);
  if (cur != NULL)
  {
    do
    {
      mark(cur);
      cur = *((void **) cur);
    }
    while (cur != NULL);
  }
  step(b);
  cur = *((void **) b);
  if (cur != NULL)
  {
    do
    {
      s32 f = *((s32 *) (((u8 *) cur) + 0x58));
      if (f & 1) { mark(cur); }
      cur = *((void **) cur);
    }
    while (cur != NULL);
  }
}
'''


def test_the_second_walk_gets_a_local_of_its_own_whose_name_is_free():
    (family, text), = variants(SOURCE, 'walk')
    assert family == FAMILY
    assert '  void *cur_2;\n' in text and text.count('cur_2') == 8
    assert text.index('cur = *((void **) a);') < text.index('cur_2 = *((void **) b);')
    first = text[text.index('var_a1_2 = a;'):text.index('step(b);')]
    assert 'cur_2' not in first and first.count('cur') >= 5
    # a name that exists is stepped over
    (_, other), = variants(SOURCE.replace('void *var_a1_2;', 'void *cur_2;').replace('var_a1_2 = a;', 'cur_2 = a;'), 'walk')
    assert 'cur_3' in other


def test_a_cursor_read_outside_its_walks_or_walked_once_is_left_alone():
    assert variants(SOURCE.replace('  step(b);', '  step(cur);'), 'walk') == []
    assert variants(SOURCE.replace('cur = *((void **) b);', 'cur = a;'), 'walk') != []
    single = SOURCE[:SOURCE.index('  step(b);')] + '}\n'
    assert variants(single, 'walk') == []
    assert variants(SOURCE.replace('if (cur != NULL)', 'if (b != NULL)'), 'walk') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'sequential_cursor_split' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'sequential_cursor_split':
            assert registry.problems(repair) == []
