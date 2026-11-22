from decomprepair import arm_pointer_split_repairs as repair

JOINED = '''void f(void *a, s32 i) {
  f32 v;
  void *p;
  void *q;
  if (i == 5) {
    q = *(void **) a;
    p = *(void **) q;
    v = *(f32 *) (((char *) p) + 0x14) + 1.0f;
  } else {
    p = *(void **) ((char *) a + 4);
    v = *(f32 *) (((char *) p) + 0x2C) * 0.5f;
  }
  *(f32 *) (((char *) p) + 0x14) = v;
  g(a);
}
'''


def test_the_pointer_is_split_per_arm_and_the_store_moves_into_each_arm():
    out = repair.variants(JOINED, 'f')[0][1]
    assert 'void *p_arm1;' in out and 'void *p_arm2;' in out
    assert '*(f32 *) (((char *) p_arm1) + 0x14) = *(f32 *) (((char *) p_arm1) + 0x14) + 1.0f;' in out
    assert '*(f32 *) (((char *) p_arm2) + 0x14) = *(f32 *) (((char *) p_arm2) + 0x2C) * 0.5f;' in out
    assert '*(f32 *) (((char *) p) + 0x14) = v;' not in out


def test_a_pointer_or_value_read_after_the_store_is_left_alone():
    assert repair.variants(JOINED.replace('  g(a);', '  g(p);'), 'f') == []
    assert repair.variants(JOINED.replace('  g(a);', '  g(v);'), 'f') == []


def test_no_variant_without_an_else_arm():
    source = JOINED.replace('  } else {\n    p = *(void **) ((char *) a + 4);', '  }\n  {\n    p = *(void **) ((char *) a + 4);')
    assert repair.variants(source, 'f') == []


def test_a_value_changed_again_after_its_last_top_level_write_is_left_alone():
    clamped = JOINED.replace('0x2C) * 0.5f;\n', '0x2C) * 0.5f;\n    if (v > 1.0f) {\n      v = 1.0f;\n    }\n')
    assert repair.variants(clamped, 'f') == []
