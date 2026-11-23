"""add_helper_operand_swap: the arguments of an inline `a + b` helper, passed the other way round at one call."""
from decomprepair import add_helper_operand_swap as c

SOURCE = '''extern u8 table[];
u16 next(void);
void use(u8 *p);

inline static u8 *add(s32 arg0, u8 *arg1)
{
  return arg0 + arg1;
}

void walk(s32 off)
{
  use(add(off, &table));
  use(add((next() & 0xFFFF) * 8, &table));
}
'''


def test_one_child_per_call_with_casts_to_the_other_parameter_type():
    out = [text for _, text in c.variants(SOURCE, 'walk')]
    assert len(out) == 2
    assert 'use(add((s32) (&table), (u8 *) (off)));' in out[0]
    assert 'use(add((s32) (&table), (u8 *) ((next() & 0xFFFF) * 8)));' in out[1]
    assert 'use(add((next() & 0xFFFF) * 8, &table));' in out[0]


def test_the_helper_body_itself_is_not_a_call_site():
    assert all('return arg0 + arg1;' in text for _, text in c.variants(SOURCE, 'walk'))


def test_nothing_without_an_add_helper():
    assert c.variants('void f(s32 a, s32 b)\n{\n    g(a + b);\n}\n', 'f') == []


def test_a_helper_that_does_more_than_add_is_not_one():
    source = SOURCE.replace('return arg0 + arg1;', 'return arg0 + arg1 + 1;')
    assert c.variants(source, 'walk') == []
