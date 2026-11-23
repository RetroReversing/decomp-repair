"""A byte's sign bit tested with a mask, written as a signed byte compared with zero."""
import re

from decomprepair.byte_sign_test import variants

CODE = '''void f(u8 *p, int k)
{
  u8 n;
  n = p[0x19A] - 1;
  p[0x19A] = n;
  if (n & 0x80)
  {
    p[0x19A] = 15;
  }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_an_unsigned_byte_tested_with_the_sign_mask_becomes_a_signed_compare():
    [(family, child)] = variants(CODE, 'f')
    assert family == 'byte_sign_test'
    text = squash(child)
    assert 's8 n;' in text and 'u8 n;' not in text
    assert 'if (n < 0)' in text
    assert 'p[0x19A] = n;' in text


def test_a_negated_test_and_a_signed_local():
    code = CODE.replace('u8 n;', 's8 n;').replace('if (n & 0x80)', 'if (!(n & 0x80))')
    [(_, child)] = variants(code, 'f')
    assert 'if (n >= 0)' in squash(child) and 's8 n;' in child


def test_a_mask_used_elsewhere_is_left_alone():
    assert variants(CODE.replace('p[0x19A] = 15;', 'k = n & 0x80;'), 'f') == []


def test_other_processors_are_not_offered_it():
    assert variants(CODE, 'f', 'ppc') == []
