"""The command-emission shape from a KMC-compiled N64 function (810 -> 0): a shared cursor and value across arms.

The chain is checked on a small function of the same shape, never on game code: split the union, give each arm
its own names, copy the shared tail into the arms, copy a goto'd body where it is jumped from."""
from decomprepair import join_tail_arm_split_repairs as repair

UNION = '''void f(s32 i) {
  union {
    s32 *pointer;
    s32 value;
  } phase;
  phase.value = i & 7;
  if (phase.value == 1) {
    phase.pointer = g_cursor;
    g_cursor = phase.pointer + 2;
  }
}
'''

ARMS = '''void f(s32 i) {
  s32 *p;
  s32 v;
  if (i & 3) {
    p = g_cursor;
    g_cursor = p + 2;
    p[0] = 0xDE000000;
    v = 5;
  } else {
    p = g_cursor;
    g_cursor = p + 2;
    p[0] = 0xDE000000;
    v = 7;
  }
  p[1] = v;
  g_done = 1;
}
'''

LABEL = '''void f(s32 i) {
  s32 *p;
  s32 v;
  if (i & 3) {
    p = g_cursor;
    g_cursor = p + 2;
    v = 5;
    p[0] = 0xDE000000;
    goto join;
  }
  p = g_cursor;
  g_cursor = p + 2;
  v = 7;
  p[0] = 0xDE000000;
join:
  p[1] = v;
  g_done = 1;
}
'''

COPY = '''void f(s32 i) {
  s32 *p;
  if (i == 1) {
    goto emit;
  }
  if (i == 2) {
    g_two = 1;
  } else if (i == 4) {
    p = g_cursor;
emit:
    g_cursor = p + 2;
    p[0] = 0xDE000000;
  }
  g_done = 1;
}
'''


def test_a_union_of_phases_becomes_one_local_per_member():
    (family, out), = repair.union_variants(UNION, 'f')
    assert family == 'phase_union_unshare'
    assert 's32 *phase_pointer;' in out and 's32 phase_value;' in out and 'union' not in out
    assert 'phase_value == 1' in out and 'g_cursor = phase_pointer + 2;' in out


def test_a_union_used_as_a_whole_is_left_alone():
    assert repair.union_variants(UNION.replace('phase.value = i & 7;', 'g_copy = phase;'), 'f') == []


def test_the_statement_after_an_if_else_is_copied_into_both_arms_with_names_of_their_own():
    out = [text for _, text in repair.tail_variants(ARMS, 'f')]
    assert out, 'the join was not offered'
    text = out[0]
    assert 'p_a1[1] = v_a1;' in text and 'p_a2[1] = v_a2;' in text
    assert '\n  p[1] = v;' not in text and 's32 *p;' not in text  # declared only in the arms now
    assert 'g_done = 1;' in text


def test_a_value_read_after_the_join_keeps_the_shared_name():
    for _, text in repair.tail_variants(ARMS.replace('  g_done = 1;', '  g_done = v;'), 'f'):
        assert 'v_a1' not in text and 's32 v;' in text


def test_an_arm_that_jumps_away_does_not_get_the_tail():
    jumping = ARMS.replace('    v = 5;\n', '    v = 5;\n    goto out;\n').replace('  g_done = 1;\n', 'out:\n  g_done = 1;\n')
    for _, text in repair.tail_variants(jumping, 'f'):
        assert 'p_a1[1] = v_a1;' not in text


def test_a_label_the_arms_goto_moves_after_its_statement_which_each_arm_now_carries():
    out = [text for _, text in repair.tail_variants(LABEL, 'f')]
    assert out
    text = out[0]
    assert 'p_a1[1] = v_a1; goto join;' in text
    assert text.index('p[1] = v;') < text.index('join:')


def test_the_one_shot_wrappers_of_a_touched_arm_are_dropped_in_a_variant_of_their_own():
    wrapped = ARMS.replace('    g_cursor = p + 2;\n    p[0] = 0xDE000000;\n    v = 5;',
                           '    do { g_cursor = p + 2; } while (0);\n    p[0] = 0xDE000000;\n    v = 5;')
    texts = [text for _, text in repair.tail_variants(wrapped, 'f')]
    assert any('while (0)' in text for text in texts) and any('while (0)' not in text for text in texts)


def test_a_private_name_in_one_arm_is_renamed_where_the_other_uses_are_elsewhere():
    source = ARMS.replace('  p[1] = v;\n', '').replace('    v = 5;', '    p[1] = 5;').replace('    v = 7;', '    p[1] = 7;')
    out = repair.rename_variants(source, 'f')
    assert out and all(family == 'arm_private_rename' for family, _ in out)
    assert any('p_a1' in text and 'p_a2' in text for _, text in out)


def test_a_name_read_after_the_arms_is_not_renamed():
    assert repair.rename_variants(ARMS.replace('  g_done = 1;', '  g_done = *p;'), 'f') == []


def test_a_goto_to_a_body_in_a_later_arm_is_replaced_by_a_copy_of_that_body():
    out = repair.copy_variants(COPY, 'f')
    assert out and out[0][0] == 'goto_body_copy'
    text = out[0][1]
    assert 'goto emit' not in text and 'emit:' not in text
    assert text.count('p[0] = 0xDE000000;') == 2 and 'else {' in text


def test_a_label_with_two_gotos_is_not_copied():
    twice = COPY.replace('  g_done = 1;', '  if (g_done) { goto emit; }\n  g_done = 1;')
    assert repair.copy_variants(twice, 'f') == []


def test_every_family_is_named_and_offered_through_variants():
    families = {family for family, _ in repair.variants(UNION, 'f') + repair.variants(ARMS, 'f')
                + repair.variants(LABEL, 'f') + repair.variants(COPY, 'f')}
    assert families <= set(repair.FAMILIES) and {'phase_union_unshare', 'join_tail_arm_split', 'goto_body_copy'} <= families
