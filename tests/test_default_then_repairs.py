"""`default_into_then`: a default value written as the then arm of the inverted test, the body as the `else`.

From a KMC-compiled N64 function (gcc 2.7.2): a halfword read guarded by `!= 0xFF` was 95 -> 80 with the default as the
then arm. Checked on a small function of the same shape, never on game code."""
from decomprepair import default_else_repairs as repair

SOURCE = '''void f(u8 *a, u16 *out) {
  u16 v;
  v = 0xA0;
  if (a[8] != 0xFF)
  {
    v = *(u16 *)(a + 4);
  }
  *out = v;
}
'''


def test_the_default_becomes_the_then_arm_of_the_inverted_test():
    out = dict((family, text) for family, text in repair.variants(SOURCE, 'f'))
    text = out['default_into_then']
    assert 'if (a[8] == 0xFF)' in text and 'v = 0xA0;' in text and 'else' in text
    assert text.index('v = 0xA0;') < text.index('else') < text.index('v = *(u16 *)(a + 4);')
    assert text.count('v = 0xA0;') == 1 and '\n  v = 0xA0;\n  if' not in text


def test_the_plain_else_form_is_still_offered_beside_it():
    families = [family for family, _ in repair.variants(SOURCE, 'f')]
    assert families[:2] == ['default_into_else', 'default_into_then']


def test_a_test_that_cannot_be_inverted_offers_no_then_form():
    source = SOURCE.replace('a[8] != 0xFF', 'a[8] && a[9]')
    assert 'default_into_then' not in [family for family, _ in repair.variants(source, 'f')]


def test_a_body_that_reads_the_default_first_is_left_alone():
    source = SOURCE.replace('v = *(u16 *)(a + 4);', 'v = v + 1;')
    assert repair.variants(source, 'f') == []


def test_every_family_is_named():
    assert set(repair.FAMILIES) >= {'default_into_else', 'else_into_default', 'default_into_then'}


BLOCKED = '''void f(u8 *a, u16 *out, u16 *tbl) {
  u16 v;
  {
    *tbl = 1;
    v = 0x37;
  }
  if (((a[8] == 0) | (a[8] == 2)) == 0)
  {
    v = *(u16 *)(a + 4) * 2;
  }
  *out = v;
}
'''


def test_a_default_that_ends_a_bare_block_moves_into_the_else_of_the_if_after_it():
    out = dict((family, text) for family, text in repair.variants(BLOCKED, 'f'))
    text = out['default_into_else']
    assert text.index('else') > text.index('v = *(u16 *)(a + 4) * 2;') and text.count('v = 0x37;') == 1
    assert text.index('v = 0x37;') > text.index('else')
    assert text.index('*tbl = 1;') < text.index('if (')


def test_a_default_at_the_end_of_a_loop_or_if_body_is_not_moved_out_of_it():
    guarded = BLOCKED.replace('  {\n    *tbl = 1;', '  if (a[0])\n  {\n    *tbl = 1;')
    assert repair.variants(guarded, 'f') == []
