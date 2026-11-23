"""Float literals stored after a call, kept in locals assigned right after it."""
import re

from decomprepair.float_literal_locals import FAMILY, variants

CODE = '''typedef float f32;
typedef struct { f32 a, b, c, d; } Rec;
extern f32 compute(f32);
void init(Rec *r, f32 *out)
{
    *out = compute(3.0f);
    r->a = 1.0f;
    r->b = 0.125f;
    r->c = 1.0f;
    r->d = 1.0f;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_literals_become_locals_after_the_call_and_before_it():
    children = variants(CODE, 'init')
    assert [family for family, _ in children] == [FAMILY] * 3
    split, after, before = (squash(text) for _, text in children)
    assert 'f32 lit_1p0; f32 lit_0p125;' in split and 'f32 lit_1p0; f32 lit_0p125;' in after
    assert 'lit_r = compute(3.0f); lit_1p0 = 1.0f; lit_0p125 = 0.125f; *out = lit_r;' in split
    assert '*out = compute(3.0f); lit_1p0 = 1.0f; lit_0p125 = 0.125f; r->a = lit_1p0; r->b = lit_0p125;' in after
    assert 'lit_1p0 = 1.0f; lit_0p125 = 0.125f; *out = compute(3.0f); r->a = lit_1p0;' in before
    assert 'r->d = lit_1p0;' in after


def test_a_run_of_fewer_than_three_literal_stores_or_one_distinct_value_is_left_alone():
    assert variants(CODE.replace('    r->c = 1.0f;\n    r->d = 1.0f;\n', ''), 'init') == []
    assert variants(CODE.replace('0.125f', '1.0f'), 'init') != []  # (one repeated literal is enough)
