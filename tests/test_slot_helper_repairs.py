from decomprepair import slot_helper_repairs as repair

SOURCE = '''void f(void *arg0, s32 idx) {
  void **slot;
  slot = (idx * 4) + gTable;
  call(arg0 + 0x24, *slot, 1.0f, 10.0f);
  call2(arg0, *slot);
}
'''


def test_the_helper_takes_the_table_as_a_parameter():
    out = [v for _, v in repair.variants(SOURCE, 'f')]
    plain = out[0]
    assert 'inline static void **__repair_slot(char *b, s32 i)' in plain
    assert 'slot = __repair_slot(gTable, idx);' in plain
    assert 'return (void **) (b + i * 4);' in plain
    assert '(idx * 4) + gTable' not in plain


def test_a_float_literal_of_the_next_call_is_held_in_a_local_first():
    out = [v for _, v in repair.variants(SOURCE, 'f')]
    held = [v for v in out if '__repair_lit = 1.0f;' in v]
    assert held and 'call(arg0 + 0x24, *slot, __repair_lit, 10.0f);' in held[0]
    assert held[0].index('__repair_lit = 1.0f;') < held[0].index('slot = __repair_slot')
    assert 'f32 __repair_lit;' in held[0]


def test_a_table_that_is_a_local_is_left_alone():
    assert repair.variants(SOURCE.replace('  void **slot;', '  void **slot;\n  char gTable[8];'), 'f') == []
