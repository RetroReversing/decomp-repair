"""Two neighbouring initialised locals written in the other order."""
from decomprepair import registry
from decomprepair.adjacent_init_swap import FAMILY, variants

SOURCE = '''void walk(u8 *base, s32 n)
{
  s32 i;
  for (i = 0; i < n; i++)
  {
    void *a = NULL;
    void *b = NULL;
    s32 c = 0;
    if (base[i] & 4) { a = base + i; } else { b = base + i; }
    use(a, b, c);
  }
}
'''


def test_each_adjacent_pair_is_offered_swapped_once():
    found = variants(SOURCE, 'walk')
    assert [family for family, _ in found] == [FAMILY, FAMILY]
    first, second = (text for _, text in found)
    assert first.index('void *b = NULL;') < first.index('void *a = NULL;') < first.index('s32 c = 0;')
    assert second.index('void *a = NULL;') < second.index('s32 c = 0;') < second.index('void *b = NULL;')
    assert first.count('\n') == SOURCE.count('\n')


def test_initialisers_that_refer_to_each_other_or_are_not_adjacent_are_left_alone():
    assert variants(SOURCE.replace('void *b = NULL;', 'void *b = a;'), 'walk') == []
    apart = variants(SOURCE.replace('    void *b = NULL;\n    s32 c = 0;\n', '    void *b = NULL;\n    h();\n    s32 c = 0;\n'), 'walk')
    assert len(apart) == 1 and apart[0][1].index('void *b = NULL;') < apart[0][1].index('void *a = NULL;')


def test_the_module_declares_itself_to_the_registry():
    assert 'adjacent_init_swap' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'adjacent_init_swap':
            assert registry.problems(repair) == []
