"""A global word passed to a call outside a loop, read through a pointer local (a probe handler, 60 -> 0)."""
from decomprepair import registry
from decomprepair.call_global_pointer_arg import FAMILY, variants

SOURCE = """extern const s32 gMessage;
extern s32 gOther;
extern volatile s32 gPort;
extern char buffer[];
void show(s32, s32, char *, s32, s32, s32, s32, s32, s32, s32, s32);
void tick(s32 n)
{
  show(0, gMessage, buffer, -1, -1, 1, 0, 0, 6, 0, 0x3C);
  show(1, gOther, buffer, -1, -1, 1, 0, 0, 6, 0, 0x3C);
  show(2, gPort, buffer, -1, -1, 1, 0, 0, 6, 0, 0x3C);
  show(3, gOther, buffer, n++, -1, 1, 0, 0, 6, 0, 0x3C);
}
"""


def children(source=SOURCE, header=''):
    return [text for family, text in variants(source, 'tick', header) if family == FAMILY]


def test_each_passed_word_is_read_through_a_pointer_local_one_child_each_and_all_together():
    first, second, both = children()
    assert '{ const s32 *gMessage_ptr = &gMessage; show(0, *gMessage_ptr, buffer, -1, -1, 1, 0, 0, 6, 0, 0x3C); }' in first
    assert 'show(1, gOther,' in first
    assert '{ const s32 *gOther_ptr = &gOther; show(1, *gOther_ptr, buffer,' in second and 'show(0, gMessage,' in second
    assert '*gMessage_ptr' in both and '*gOther_ptr' in both


def test_volatile_words_impure_calls_and_taken_names_are_left_alone():
    for text in children():
        assert 'show(2, gPort,' in text and 'show(3, gOther, buffer, n++' in text
    assert len(children(SOURCE.replace('void tick(s32 n)', 'void tick(s32 gMessage_ptr)'))) == 1


def test_a_header_declaration_counts():
    source = SOURCE.replace('extern s32 gOther;\n', '')
    assert any('*gOther_ptr' in text for text in children(source, 'extern s32 gOther;\n'))


def test_the_registry_runs_the_module():
    assert FAMILY in {family for rep in registry.declared() for family in rep.families}
