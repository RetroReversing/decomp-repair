"""An early exit that repeats the function's ending stores, written once after an inverted test."""
import re

from decomprepair.shared_return_tail_merge import _invert, variants

CODE = '''void f(S *s)
{
  int p;
  p = s->slot;
  if (p == (-1))
  {
    *((s16 *) inline_fn23((char *) s, 0x178)) = 0;
    return;
  }
  release(p);
  s->slot = -1;
  *((s16 *) inline_fn2((char *) s, 0x178)) = 0;
  return;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_early_exits_stores_are_written_once_after_the_inverted_test():
    [(family, child)] = variants(CODE, 'f')
    assert family == 'shared_return_tail_merge'
    text = squash(child)
    assert 'if (p != (-1)) { release(p); s->slot = -1; } *((s16 *) inline_fn2((char *) s, 0x178)) = 0; return; }' in text
    assert text.count('0x178') == 1


def test_an_exit_whose_stores_differ_is_left_alone():
    assert variants(CODE.replace('0x178)) = 0;\n    return;', '0x17A)) = 0;\n    return;'), 'f') == []


def test_a_tail_with_a_label_or_a_declaration_is_left_alone():
    assert variants(CODE.replace('release(p);', 'again: release(p);'), 'f') == []
    assert variants(CODE.replace('release(p);', 'int q = 1; release(q);'), 'f') == []


def test_an_else_is_left_alone_and_a_returned_value_is_kept():
    assert variants(CODE.replace('  release(p);', '  else { x(); }\n  release(p);'), 'f') == []
    valued = CODE.replace('void f', 'int f').replace('    return;', '    return 1;').replace('  return;\n}', '  return 1;\n}')
    [(_, child)] = variants(valued, 'f')
    assert squash(child).strip().endswith('= 0; return 1; }')


def test_the_negation_swaps_one_comparison_and_wraps_anything_else():
    assert _invert('a == (-1)') == 'a != (-1)'
    assert _invert('x < 3') == 'x >= 3'
    assert _invert('f(a, b) == 2') == 'f(a, b) != 2'
    assert _invert('a && b') == '!(a && b)'
    assert _invert('a >> 2') == '!(a >> 2)'
    assert _invert('p->next') == '!(p->next)'


def test_other_processors_are_not_offered_it():
    assert variants(CODE, 'f', 'ppc') == []
