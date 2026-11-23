"""A literal held in a local and stored through several statements, written as one chained assignment."""
import re

from decomprepair.float_literal_chain import variants

FENCED = '''void f(char *p)
{
  f32 zero;
  g(1);
  do
  {
    D_8 = *((f32 *) (((char *) p) + 0x2C)); zero = 0.0f;
  }
  while (0);
  *((f32 *) (((char *) p) + 0x2C)) = zero;
  *((f32 *) (((char *) p) + 0x28)) = zero;
  *((f32 *) (((char *) p) + 0x24)) = zero;
  h();
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(source, name='f'):
    return [_squash(text) for family, text in variants(source, name) if family == 'float_literal_chain']


def test_the_stores_become_one_chain_that_runs_in_their_order():
    found = _all(FENCED)
    chain = '*((f32 *) (((char *) p) + 0x24)) = *((f32 *) (((char *) p) + 0x28)) = *((f32 *) (((char *) p) + 0x2C)) = 0.0f;'
    assert found and all(chain in t for t in found)
    assert all('zero =' not in t and '= zero' not in t for t in found)


def test_the_fence_is_kept_in_one_child_and_taken_off_in_another():
    found = _all(FENCED)
    assert any('do { D_8 = *((f32 *) (((char *) p) + 0x2C)); } while (0);' in t for t in found)
    assert any('do' not in t and 'D_8 = *((f32 *) (((char *) p) + 0x2C));' in t for t in found)


def test_a_plain_run_without_a_fence():
    source = 'void f(int *a, int *b)\n{\n  s32 z;\n  z = 0;\n  *a = z;\n  *b = z;\n}\n'
    assert any('*b = *a = 0;' in t for t in _all(source))


def test_a_local_read_later_or_a_single_store_is_left_alone():
    later = FENCED.replace('  h();\n', '  h(zero);\n')
    assert _all(later) == []
    single = 'void f(int *a)\n{\n  s32 z;\n  z = 0;\n  *a = z;\n}\n'
    assert _all(single) == []
