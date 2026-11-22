import re

from decomprepair import parameter_copy_drop_repairs
from decomprepair import walk_shape_repairs as walk

# a recency list walked for nodes that overlap a range, logging what had to be loaded (a block cache, written the way
# m2c does: a pointer local for the log entry, the scratch shared by the arms, the node copied into the loop variable)
SOURCE = """void lookup(Out *out, u32 arg1, s32 arg2, s32 key)
{
  u32 rows[3][2];
  u32 hi;
  Node *node;
  Node *next;
  Ent *e;
  u32 a0;
  u32 a1;
  s32 count;
  s32 size;
  u32 start;
  u32 v;
  Node *free_head;

  start = arg1;
  size = arg2;
  hi = start + size;
  count = 0;
  node = list_head;
  while (node != NULL) {
    next = node->next;
    if (node->tag == key && node->addr < hi && start < node->addr) {
      a0 = node->addr;
      a1 = node->len;
      if (start + size >= a0 + 0x600)
        v = 0x600 - a1;
      else
        v = ((start + size - (a0 + a1)) + 0xFF) & ~0xFF;
      e = &log_table[log_count];
      e->base = a0 + a1;
      e->count = v;
      e->data = node->data;
      log_count++;
      if (start < a1) {
        a0 = size - (node->addr - start);
        rows[1][(u16) count] = a0;
        count++;
        size -= a0;
      } else if (a1 + node->len < start + size) {
        a0 = node->addr + node->len - start;
        rows[1][(u16) count] = a0;
        count++;
        size -= a0;
        start = node->addr + node->len;
      } else {
        rows[1][(u16) count] = size;
        size = 0;
        rows[2][(u16) count] = start;
        rows[0][(u16) count] = node->data + (start - a1);
        count++;
        break;
      }
    }
    node = next;
  }
  while (size != 0) {
    node = free_list;
    if (free_list != NULL) {
      free_list = node->prev;
      list_head = node;
    } else {
      node = list_tail;
      list_tail = node->prev;
    }
    size = size - 0x600 + v;
    start -= v - 0x600;
  }
  if ((count & 0xFFFF) == 1) {
    out->a = rows[0][0];
    out->d = 0;
    out->c = rows[1][0];
    return;
  }
  out->a = rows[0][1];
}
"""
NAME = 'lookup'


def _of(family, source=SOURCE):
    return [text for label, text in family(source, NAME)]


def test_the_log_pointer_is_written_at_each_store():
    (text, *_) = _of(walk.element_pointer_inline)
    assert 'log_table[log_count].base = a0 + a1;' in text
    assert 'log_table[log_count].data = node->data;' in text
    assert 'e = &log_table' not in text
    assert 'Ent *e;' not in text


def test_a_pointer_that_is_still_used_keeps_its_declaration():
    source = SOURCE.replace('      log_count++;', '      log_count++;\n      sink(e);')
    assert _of(walk.element_pointer_inline, source) == []


def test_the_first_read_of_a_conditions_value_is_the_assignment():
    (text,) = _of(walk.condition_capture)
    assert 'node->addr < hi && start < node->addr' not in text
    assert 'if (node->tag == key && (a0 = node->addr) < hi && start < a0) {' in text
    assert '      a0 = node->addr;' not in text


def test_a_sum_in_the_test_and_the_arms_is_computed_once():
    (text,) = _of(walk.value_reuse_before_branch)
    assert '      v = start + size;\n      if (v >= a0 + 0x600)' in text
    assert 'v = ((v - (a0 + a1)) + 0xFF) & ~0xFF;' in text


def test_a_scratch_assigned_first_in_an_arm_is_declared_in_the_arm():
    texts = _of(walk.arm_scoped_scratch)
    one = [t for t in texts if t.count('u32 a0;') == 2]
    both = [t for t in texts if t.count('u32 a0;') == 3]
    assert one and both
    assert re.search(r'\{\n\s*u32 a0;\n\s*a0 = size - \(node->addr - start\);', both[0])
    # the else arm never assigns the scratch first, and the arms before a read of it later are left alone
    assert not any('else {\n        u32 a0;' in t for t in texts)


def test_a_reassociable_expression_is_split_into_two_statements():
    texts = _of(walk.reassociation_temp)
    assert any('n = size - 0x600;\n    size = n + v;' in t for t in texts)
    assert any('m = v - 0x600;\n    start -= m;' in t for t in texts)


def test_the_node_is_a_temporary_handle_copied_into_the_loop_variable():
    texts = _of(walk.arm_handle_copy)
    assert texts
    first = texts[0]
    assert 'if (free_list != NULL) {\n      t = free_list;' in first
    assert 'free_list = t->prev;' in first and 'node = t;' in first
    assert 'Node *t;' in first


def test_independent_stores_move_and_dependent_ones_stay():
    texts = _of(walk.store_run_move)
    assert any(t.index('out->c = rows[1][0];') < t.index('out->d = 0;') for t in texts)
    # `size = 0` reads what the store before it reads: they never swap
    assert not any(t.index('size = 0;') < t.index('rows[1][(u16) count] = size;') for t in texts
                   if 'rows[1][(u16) count] = size;' in t)


def test_the_chain_applies_every_step_that_is_the_same_wherever_it_applies():
    ((label, text),) = walk.chain(SOURCE, NAME)
    assert label == walk.FAMILY_CHAIN
    assert 'log_table[log_count].base' in text and '(a0 = node->addr)' in text
    assert 'v = start + size;' in text and 'n = size - 0x600;' in text and 'node = t;' in text
    assert walk.chain(text, NAME) == [] or walk.chain(text, NAME)[0][1] != text


def test_every_family_is_offered_and_named():
    labels = {label for label, _ in walk.variants(SOURCE, NAME)}
    assert labels == set(walk.FAMILIES)


def test_nothing_is_offered_for_a_function_it_does_not_apply_to():
    for source in ('void f(void) { }', 'int g(int x) { return x + 1; }', 'void f(void) { goto a; a: ; }'):
        assert walk.variants(source, 'f' if 'f(' in source else 'g') == []


def test_both_parameter_copies_are_dropped_as_one_child():
    source = """void f(Out *out, u32 arg1, s32 arg2)
{
  u32 start;
  s32 size;
  start = arg1;
  size = arg2;
  out->a = start + size;
}
"""
    children = [text for _, text in parameter_copy_drop_repairs.variants(source, 'f')]
    both = [t for t in children if 'start' not in t and 'size' not in t]
    assert both and 'out->a = arg1 + arg2;' in both[0]
