"""Two cases that trade table destinations when only one of them is a written label."""
from decomprepair import targeted_switch_labels as labels

CODE = '''void f(void *arg0) {
  u16 t;

  t = *(u16 *)((s8 *)arg0 + 0x24A);
  switch (t) {
    case 1:
      a();
      return;
    case 12:
      b();
      /* fallthrough */
    default:
      return;
  }
}
'''


def rows(first=7, second=12):
    return [{'table': 1, 'case': first, 'target': 0x10, 'candidate': 0x18},
            {'table': 1, 'case': second, 'target': 0x18, 'candidate': 0x10}]


def squash(text):
    return ' '.join(text.split())


def test_the_written_label_moves_to_the_missing_case_and_takes_the_join_label():
    found = dict(labels.default_swap_variants(CODE, 'f', rows()))
    text = squash(found['linked_switch_default_swap'])
    assert 'case 7: b(); /* fallthrough */ case 12: default: return;' in text
    assert 'case 1: a(); return;' in text


def test_the_public_entry_offers_it():
    assert 'linked_switch_default_swap' in dict(labels.variants(CODE, 'f', rows()))


def test_hex_labels_keep_their_spelling():
    text = dict(labels.default_swap_variants(CODE.replace('case 12:', 'case 0xc:'), 'f', rows(7, 12)))
    assert 'case 0x7:' in squash(text['linked_switch_default_swap'])
    text = dict(labels.default_swap_variants(CODE.replace('case 12:', 'case 0xc:'), 'f', rows(16, 12)))
    assert 'case 0x10:' in squash(text['linked_switch_default_swap'])
    assert 'case 0xc: default:' in squash(text['linked_switch_default_swap'])


def test_two_written_labels_are_a_relabel_not_a_default_swap():
    both = CODE.replace('case 1:', 'case 7:')
    assert labels.default_swap_variants(both, 'f', rows()) == []


def test_rows_that_are_not_a_swap_are_left_alone():
    one_way = [{'table': 1, 'case': 7, 'target': 0x10, 'candidate': 0x18},
               {'table': 1, 'case': 12, 'target': 0x20, 'candidate': 0x10}]
    assert labels.default_swap_variants(CODE, 'f', one_way) == []
    assert labels.default_swap_variants(CODE, 'f', rows()[:1]) == []


def test_a_switch_without_default_is_left_alone():
    assert labels.default_swap_variants(CODE.replace('default:', ''), 'f', rows()) == []
