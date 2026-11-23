"""default_expression_into_else / _then: `len = n * 4; if (n > 0x100) { len = 0x400; }` with the clamp as the then arm.

From a 222-instruction stream refill built by IDO 7.1: a read length was `n * 4` unless `n > 0x100`, and the target's
branch layout (`bnez; sll` and a `b` over the constant) came from `if (n > 0x100) { len = 0x400; } else { len = n * 4; }`,
not from the default before the test (655 -> 555 as one step of the match). Checked on a small function of the same shape,
never on game code."""
from decomprepair import default_else_repairs as repair

SOURCE = '''s32 pick(Ring *p, u32 n)
{
  s32 len;
  len = n * 4;
  if (n > 0x100)
  {
    len = 0x400;
  }
  return fill(p, len);
}
'''


def out(source=SOURCE):
    return dict((family, text) for family, text in repair.variants(source, 'pick'))


def test_the_expression_default_moves_into_the_else_arm():
    text = out()['default_expression_into_else']
    assert text.count('len = n * 4;') == 1 and '\n  len = n * 4;\n  if' not in text
    assert text.index('len = 0x400;') < text.index('else') < text.index('len = n * 4;')


def test_the_inverted_test_form_is_offered_too():
    text = out()['default_expression_into_then']
    assert 'if (n <= 0x100)' in text and text.index('len = n * 4;') < text.index('else') < text.index('len = 0x400;')


def test_a_default_with_a_call_is_left_alone():
    assert out(SOURCE.replace('len = n * 4;', 'len = scale(n);')) == {}


def test_a_test_with_a_call_is_left_alone():
    assert out(SOURCE.replace('if (n > 0x100)', 'if (big(n))')) == {}


def test_a_default_that_reads_the_local_is_left_alone():
    assert out(SOURCE.replace('len = n * 4;', 'len = len * 4;')) == {}


def test_an_arm_that_sets_the_local_only_conditionally_is_left_alone():
    source = SOURCE.replace('    len = 0x400;\n', '    if (n > 0x200)\n    {\n      len = 0x400;\n    }\n')
    assert out(source) == {}


def test_the_literal_and_identifier_defaults_keep_their_own_families():
    source = SOURCE.replace('len = n * 4;', 'len = 0;')
    assert set(out(source)) == {'default_into_else', 'default_into_then'}


def test_every_family_is_named():
    assert {'default_expression_into_else', 'default_expression_into_then'} <= set(repair.FAMILIES)
