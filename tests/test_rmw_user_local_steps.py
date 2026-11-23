"""A word read-modify-write written as a local updated by separate statements (a player update, 60 -> 0)."""
from decomprepair.rmw_user_local_steps import FAMILY, REPAIR, variants

SOURCE = """void apply(void *obj)
{
  s32 flag;
  void *rec;
  rec = *((void **) (((char *) obj) + 0x6C));
  flag = ((Field_s32 *) (((char *) obj) + 0x60))->v;
  if (flag & 0x20)
  {
    mark = ((Field_f32 *) (((char *) rec) + 0x1B0))->v;
    ((Field_f32 *) (((char *) rec) + 0x1B0))->v = 0.0f;
    ((Field_u32 *) (((char *) rec) + 0x18C))->v = (u32) ((((Field_u32 *) (((char *) rec) + 0x18C))->v & 0xFFFF0FFF) | 0x7000);
  }
  use(mark);
}
"""


def children(source):
    return [text for family, text in variants(source, 'apply') if family == FAMILY]


def test_the_steps_stand_where_the_expression_was_in_the_last_declaration_place():
    found = children(SOURCE)
    assert found
    inplace = [t for t in found if t.index('rmw_value = ((Field_u32') > t.index('0.0f;')]
    assert inplace
    child = inplace[0]
    assert 'rmw_value &= 0xFFFF0FFF;\n    rmw_value |= 0x7000;\n    ((Field_u32 *) (((char *) rec) + 0x18C))->v = rmw_value;' in child
    assert '(u32) (' not in child.split('rmw_value |= 0x7000;')[0].split('0.0f;')[-1]


def test_the_load_and_the_steps_are_also_offered_above_the_statements_before_them():
    found = children(SOURCE)
    above = [t for t in found if t.index('rmw_value = ((Field_u32') < t.index('mark = ')]
    assert above
    assert any(t.index('rmw_value |= 0x7000;') < t.index('mark = ') for t in above)  # the steps moved too
    assert any(t.index('rmw_value |= 0x7000;') > t.index('mark = ') for t in above)  # only the load moved


def test_the_local_goes_in_three_places_in_the_declarations():
    found = children(SOURCE)
    places = {t.split('\n').index('  u32 rmw_value;') for t in found}
    assert places == {2, 3, 4}


def test_a_statement_that_does_not_read_its_own_word_is_left_alone():
    assert children(SOURCE.replace('(((Field_u32 *) (((char *) rec) + 0x18C))->v & 0xFFFF0FFF)', '(((Field_u32 *) (((char *) rec) + 0x190))->v & 0xFFFF0FFF)')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']


CAST_SOURCE = '''void f(void *s, u32 i)
{
    void *t;

    t = s;
    *((s32 *) (((char *) ((void **) (((char *) t) + 0x418))[i]) + 0x28)) = (*((s32 *) (((char *) ((void **) (((char *) t) + 0x418))[i]) + 0x28)) & ~0xFC) | 0x10;
    *((s16 *) (((char *) t) + 0x20)) = 1;
}
'''


def test_m2c_cast_form_with_an_element_base_and_a_complement_mask():
    # An effect spawner (KMC GCC 2.7.2): `markers[i]->flags = (markers[i]->flags & ~0xFC) | 0x10` in m2c's cast spelling;
    # as a local updated in steps its block's last ordering rows closed (200 -> 185 with the app's judge).
    out = [text for _, text in variants(CAST_SOURCE, 'f')]
    word = '*((s32 *) (((char *) ((void **) (((char *) t) + 0x418))[i]) + 0x28))'
    assert any(f'rmw_value = {word};\n    rmw_value &= ~0xFC;\n    rmw_value |= 0x10;\n    {word} = rmw_value;' in o
               and 's32 rmw_value;' in o for o in out)
    other = CAST_SOURCE.replace('& ~0xFC) | 0x10;', '& ~0xFC) | g;')
    assert variants(other, 'f') == []
