"""A pointer relayed through an entry local, a copy before a branchy value and a second copy after it."""
from decomprepair import pointer_relay_copy as p
from decomprepair import registry

SOURCE = '''typedef unsigned int u32;
typedef float f32;
typedef struct { u8 pad[0x12c]; f32 opacity; u32 alpha; } View;
typedef unsigned char u8;
extern View *gViews[];
extern void commit(View *);

inline static View *same(View *arg0)
{
  return arg0;
}

inline static u32 scaled(f32 arg0)
{
  return (u32) (arg0 * 255.0f);
}

void layers(void)
{
  View *view;
  f32 opacity;
  u32 i;
  i = 0;
  do
  {
    view = gViews[i];
    if (view == NULL)
    {
      goto next;
    }
    opacity = view->opacity;
    if (opacity < 0.0f) { opacity = 0.0f; }
    same(view)->alpha = scaled(opacity);
    commit(view);
    next:
    i += 1;
  }
  while (i < 6);
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'layers')]


def test_the_entry_web_is_split_and_the_pointer_relayed_across_the_value():
    (text,) = texts(SOURCE)
    assert '  View *view_entry;\n  View *view_relay;\n  u32 view_value;' in text
    assert 'view_entry = gViews[i];' in text and 'if (view_entry == NULL)' in text
    assert 'opacity = view_entry->opacity;' in text
    assert ('    view_relay = view_entry;\n    view_value = scaled(opacity);\n    view = view_relay;\n'
            '    view->alpha = view_value;\n    commit(view);') in text


def test_the_relay_is_ordered_copy_value_copy_store():
    (text,) = texts(SOURCE)
    order = [text.index(part) for part in ('view_relay = view_entry;', 'view_value = scaled(opacity);', 'view = view_relay;',
                                           'view->alpha = view_value;', 'commit(view);')]
    assert order == sorted(order)


def test_a_plain_store_is_written_without_the_helper():
    (text,) = texts(SOURCE.replace('same(view)->alpha', 'view->alpha'))
    assert 'view->alpha = view_value;' in text


def test_an_integer_cast_in_the_value_counts_as_branchy():
    (text,) = texts(SOURCE.replace('scaled(opacity)', '(u32) (opacity * 255.0f)'))
    assert 'view_value = (u32) (opacity * 255.0f);' in text


def test_a_value_without_branches_is_left_alone():
    assert not texts(SOURCE.replace('scaled(opacity)', 'opacity'))


def test_a_store_not_followed_by_a_call_on_the_pointer_is_left_alone():
    assert not texts(SOURCE.replace('commit(view);', 'commit(0);'))


def test_a_pointer_that_is_not_a_local_pointer_is_left_alone():
    assert not texts(SOURCE.replace('  View *view;\n', '').replace('void layers(void)', 'void layers(void)').replace(
        'view = gViews[i];', 'View *view = gViews[i];'))


def test_a_name_already_in_use_is_left_alone():
    assert not texts(SOURCE.replace('f32 opacity;', 'f32 opacity;\n  u32 view_value;'))


def test_the_module_declares_itself():
    repair, = [r for r in registry.declared() if r.module == 'pointer_relay_copy']
    assert registry.problems(repair) == []
