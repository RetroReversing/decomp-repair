"""A global word only passed to calls, declared read-only (a probe handler, 180 -> 60)."""
from decomprepair import registry
from decomprepair.readonly_global_arg import FAMILY, variants

SOURCE = """extern s32 gMessage;
extern s32 gCounter;
extern s32 gOther;
void show(s32, s32);
void tick(s32 n)
{
  show(0, gMessage);
  gCounter = gCounter + 1;
  show(1, gCounter);
  show(2, gOther);
  show(3, gOther);
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'tick') if family == FAMILY]


def test_a_word_only_passed_is_declared_const_one_child_each_and_all_together():
    first, second, both = children()
    assert 'extern const s32 gMessage;' in first and 'extern s32 gOther;' in first
    assert 'extern const s32 gOther;' in second and 'extern const s32 gMessage;' not in second
    assert 'extern const s32 gMessage;' in both and 'extern const s32 gOther;' in both
    assert 'extern s32 gCounter;' in both


def test_a_word_the_function_writes_or_takes_the_address_of_stays_as_it_is():
    assert len(children()) == 3
    for write in ('gOther = 1;', 'gOther++;', 'gOther += 2;', 'show(0, (s32) &gOther);'):
        text = SOURCE.replace('show(2, gOther);', write)
        assert all('extern const s32 gOther;' not in child for child in children(text))


def test_an_already_qualified_or_header_only_declaration_is_left_alone():
    qualified = SOURCE.replace('extern s32 gMessage;', 'extern volatile s32 gMessage;')
    assert all('gMessage' not in text.split('void show')[0].replace('extern volatile s32 gMessage;', '') for text in children(qualified))
    in_header = [text for family, text in variants(SOURCE.replace('extern s32 gMessage;\n', ''), 'tick', 'extern s32 gMessage;\n')]
    assert in_header and all('const s32 gMessage' not in text for text in in_header)


def test_the_registry_runs_the_module():
    assert FAMILY in {family for rep in registry.declared() for family in rep.families}
