"""A round-up to a variable power of two written as steps."""
import pytest

from decomprepair import align_up_steps as steps

DRAFT = '''s32 f(s32 size, s32 n, u32 *p) {
    s32 top;
    u32 low;
    top = ((u32) ((*p) - 1 + (1 << n)) >> n) << n;
    low = (low - 1 + (1 << n)) >> n << n;
    return top + low + size;
}
'''


def test_each_site_and_all_sites():
    out = [text for _, text in steps.variants(DRAFT, 'f')]
    assert len(out) == 3
    assert ('    top = *p;\n    top += (1 << n) - 1;\n    top = (u32) top >> n;\n    top <<= n;\n'
            '    low += (1 << n) - 1;\n    low >>= n;\n    low <<= n;\n') in out[0]


@pytest.mark.parametrize('spelling', ['((u32) (D.low + (1 << n) - 1) >> n) << n',
                                      '((u32) (D.low + ((1 << n) - 1)) >> n) << n'])
def test_other_orders_of_the_mask(spelling):
    source = f'void f(s32 n) {{\n    u32 v;\n    v = {spelling};\n    g(v);\n}}\n'
    [(_, out)] = steps.variants(source, 'f')
    assert '    v = D.low;\n    v += (1 << n) - 1;\n    v >>= n;\n    v <<= n;\n' in out


@pytest.mark.parametrize('statement', [
    'v = ((u32) (a - 1 + (1 << n)) >> n) << m;',   # another count
    'v = ((a - 1 + (1 << n)) >> n) << n;',         # a signed shift of something else
    'v = ((u32) (a + (1 << n)) >> n) << n;',       # not a round-up
    'v = ((u32) (g() - 1 + (1 << n)) >> n) << n;',
    'v = ((u32) (a & 3 - 1 + (1 << n)) >> n) << n;',
])
def test_left_alone(statement):
    assert steps.variants(f'void f(s32 a, s32 n, s32 m) {{\n    u32 v;\n    {statement}\n}}\n', 'f') == []
