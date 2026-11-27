"""A saved previous value and an advanced field, written `G = F; F += K;`."""
from decomprepair import old_value_save_compound as m

HEAD = '''void f(void *arg0)
{
  s32 temp_v1_2;
  s32 temp_v1_2_old;
  if (M2C_FIELD(arg0, s32 *, 0x80) != 0) {
'''
SPLIT = '''    temp_v1_2 = M2C_FIELD(arg0, s32 *, 0x1C);
    temp_v1_2_old = temp_v1_2;
    temp_v1_2 = temp_v1_2 + 0x800;
    M2C_FIELD(arg0, s32 *, 0x40) = temp_v1_2_old;
    M2C_FIELD(arg0, s32 *, 0x1C) = temp_v1_2;
'''
TAIL = '''  }
}
'''
WANT = '''void f(void *arg0)
{
  if (M2C_FIELD(arg0, s32 *, 0x80) != 0) {
    M2C_FIELD(arg0, s32 *, 0x40) = M2C_FIELD(arg0, s32 *, 0x1C);
    M2C_FIELD(arg0, s32 *, 0x1C) += 0x800;
  }
}
'''


def test_two_temporaries_collapse_to_a_copy_and_a_compound_step():
    # An SN64 GCC 2.8.1 object update: this exact change took the saved best from 10 to 0.
    assert m.variants(HEAD + SPLIT + TAIL, 'f') == [('old_value_save_compound', WANT)]


def test_one_temporary_and_the_step_in_the_store():
    plain = '''    temp_v1_2 = (s32) M2C_FIELD(arg0, s32 *, 0x1C);
    M2C_FIELD(arg0, s32 *, 0x40) = temp_v1_2;
    M2C_FIELD(arg0, s32 *, 0x1C) = (s32) (temp_v1_2 + 0x800);
'''
    (_, child), = m.variants(HEAD + plain + TAIL, 'f')
    assert 'M2C_FIELD(arg0, s32 *, 0x40) = M2C_FIELD(arg0, s32 *, 0x1C);\n    M2C_FIELD(arg0, s32 *, 0x1C) += 0x800;' in child
    assert 'temp_v1_2' not in child.replace('temp_v1_2_old', '')


def test_members_and_a_decrement():
    source = '''void f(P *p)
{
  s32 t;
  t = p->angle;
  p->previous = t;
  t -= step;
  p->angle = t;
}
'''
    (_, child), = m.variants(source, 'f')
    assert 'p->previous = p->angle;\n  p->angle -= step;\n' in child and 's32 t;' not in child


def test_left_alone_when_it_would_not_be_the_same_program():
    # a temporary read afterwards
    assert m.variants(HEAD + SPLIT + '    g(temp_v1_2_old);\n' + TAIL, 'f') == []
    # the advanced field stored before the old value
    swapped = SPLIT.replace('    M2C_FIELD(arg0, s32 *, 0x40) = temp_v1_2_old;\n', '')
    assert m.variants(HEAD + swapped + '    M2C_FIELD(arg0, s32 *, 0x40) = temp_v1_2_old;\n' + TAIL, 'f') == []
    # a call in between, a float field, a narrow temporary, a step that is the saved global
    assert m.variants(HEAD + SPLIT.replace('    temp_v1_2 = temp_v1_2 + 0x800;\n', '    g();\n') + TAIL, 'f') == []
    assert m.variants(HEAD + SPLIT.replace('s32 *, 0x1C', 'f32 *, 0x1C') + TAIL, 'f') == []
    assert m.variants((HEAD + SPLIT + TAIL).replace('  s32 temp_v1_2', '  s16 temp_v1_2'), 'f') == []
    assert m.variants('void f(void)\n{\n  s32 t;\n  t = D_1;\n  D_2 = t;\n  D_1 = t + D_2;\n}\n', 'f') == []
