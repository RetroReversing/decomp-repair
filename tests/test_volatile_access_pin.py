"""Two neighbouring accesses through one base pointer, both volatile, so the scheduler keeps their order."""
import re

from decomprepair.volatile_access_pin import variants

SOURCE = '''void f(void *a, void *b)
{
  s32 t;
  *((s16 *) (((char *) a) + 0x58)) = t;
  D_1 = *((f32 *) (((char *) a) + 0x24));
  t = *((u32 *) (((char *) a) + 0x5C));
  x = *((f32 *) (((char *) a) + 0x24));
  *((s8 *) (((char *) a) + 0x54)) = 1;
  *((s8 *) (((char *) a) + 0x55)) = 2;
  y = *((s32 *) (((char *) b) + 0x10));
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(source=SOURCE):
    return [_squash(text) for family, text in variants(source, 'f') if family == 'volatile_access_pin']


def test_a_store_followed_by_a_load_is_pinned_both_ways():
    found = _all()
    assert any('*((volatile s16 *) (((char *) a) + 0x58)) = t; D_1 = *((volatile f32 *) (((char *) a) + 0x24));' in t for t in found)


def test_two_loads_are_pinned_and_a_store_pair_is_not():
    found = _all()
    assert any('t = *((volatile u32 *) (((char *) a) + 0x5C)); x = *((volatile f32 *) (((char *) a) + 0x24));' in t for t in found)
    assert not any('volatile s8 *) (((char *) a) + 0x54)' in t and 'volatile s8 *) (((char *) a) + 0x55)' in t for t in found)


def test_each_proposal_touches_only_one_pair_and_other_bases_are_left_alone():
    for text in _all():
        assert text.count('volatile') == 2
        assert 'volatile s32' not in text


def test_a_store_then_load_comes_first_and_volatile_access_is_not_marked_twice():
    assert 'volatile s16' in _all()[0]
    once = variants(SOURCE, 'f')[0][1]
    assert variants(once, 'f') != [] and all(text.count('volatile') <= 4 for _, text in variants(once, 'f'))


def test_the_compact_spelling_and_a_gap_between_the_statements():
    source = 'void f(char *a)\n{\n  *(s16 *)((char *)a + 0x58) = 1;\n  x = *(f32 *)((char *)a + 0x24);\n}\n'
    assert any('*(volatile s16 *)((char *)a + 0x58) = 1; x = *(volatile f32 *)((char *)a + 0x24);' in t for t in _all(source))
    far = 'void f(char *a)\n{\n  *(s16 *)((char *)a + 0x58) = 1;\n  g();\n  x = *(f32 *)((char *)a + 0x24);\n}\n'
    assert _all(far) == []
