"""Cases the target sends to the switch's join: an arm of their own that only breaks."""
from decomprepair import targeted_switch_labels as labels

CODE = '''int f(u8 *p) {
  int v = 1;
  switch (p[0x4A]) {
    case 4:
    case 5:
      v &= -(p[0x34] == 0);
      break;
    case 18:
    case 19:
    case 20:
    default:
      v = 0;
      break;
  }
  return v;
}
'''


def rows(*cases, target=0x58, candidate=0x54):
    return [{'table': 1, 'case': case, 'target': target, 'candidate': candidate} for case in cases]


def squash(text):
    return ' '.join(text.split())


def test_cases_the_target_sends_past_the_default_arm_get_an_empty_arm():
    found = dict(labels.empty_arm_variants(CODE, 'f', rows(10, 11, 20)))
    text = squash(found['linked_switch_empty_arm'])
    assert 'case 10: case 11: case 20: break; case 18: case 19: default:' in text
    assert 'case 18: case 19: case 20:' not in text  # taken out of the arm it was stacked on
    assert 'case 4: case 5: v &= -(p[0x34] == 0); break;' in text


def test_the_public_entry_offers_it_and_a_permutation_still_relabels():
    assert 'linked_switch_empty_arm' in dict(labels.variants(CODE, 'f', rows(10, 11, 20)))
    swap = [{'table': 1, 'case': 4, 'target': 8, 'candidate': 9}, {'table': 1, 'case': 5, 'target': 9, 'candidate': 8}]
    assert 'linked_switch_empty_arm' not in dict(labels.variants(CODE, 'f', swap))


def test_a_destination_the_compiled_table_already_has_is_a_relabel_not_an_empty_arm():
    assert labels.empty_arm_variants(CODE, 'f', rows(10, 11, target=0x54, candidate=0x54)) == []
    two = rows(10) + rows(11, target=0x5C)
    assert labels.empty_arm_variants(CODE, 'f', two) == []


def test_an_arm_is_never_left_without_a_label():
    alone = CODE.replace('    case 18:\n    case 19:\n    case 20:\n    default:', '    case 20:\n    default:')
    text = squash(dict(labels.empty_arm_variants(alone, 'f', rows(10, 20))).get('linked_switch_empty_arm', ''))
    assert 'case 10: case 20: break; case 20:' not in text
    assert 'case 20: break;' in text or text == ''
    only = 'int f(int k) { int v = 1; switch (k) { case 20: v = 0; break; case 4: v = 2; break; } return v; }'
    assert labels.empty_arm_variants(only, 'f', rows(20)) == []


def test_a_switch_without_default_takes_the_group_at_its_end():
    plain = 'int f(int k) { int v = 1; switch (k) { case 4: case 6: v = 2; break; case 5: v = 3; break; } return v; }'
    [(_, text)] = labels.empty_arm_variants(plain, 'f', rows(6))
    assert 'case 4: v = 2; break; case 5: v = 3; break; case 6: break;' in squash(text)
    assert labels.empty_arm_variants(plain, 'f', rows(9)) == []  # no label, no default: nothing to move
