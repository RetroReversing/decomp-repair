"""`x = -x;` written as `x *= -1;`, which keeps a signed narrow load, and back."""
from decomprepair.narrow_negate_multiply import FAMILY, variants

SOURCE = '''typedef struct { s8 dir; } Car;
void f(Car *c, s16 *t, s32 i) {
    if (i) {
        c->dir = -c->dir;
    }
    t[i] *= -1;
}
'''


def _kids(text):
    return [s for fam, s in variants(text, 'f') if fam == FAMILY]


def test_a_negation_in_place_becomes_a_multiply_and_back():
    kids = _kids(SOURCE)
    assert SOURCE.replace('c->dir = -c->dir;', 'c->dir *= -1;') in kids
    assert SOURCE.replace('t[i] *= -1;', 't[i] = -t[i];') in kids
    assert len(kids) == 2


def test_another_value_or_a_longer_expression_is_left_alone():
    assert not _kids('void f(s32 a, s32 b) { a = -b; b = -b + 1; a *= -10; }\n')
