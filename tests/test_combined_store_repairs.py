import pytest

from decomprepair.combined_store_repairs import FAMILY, variants

SOURCE = """void f(void) {
    s32 x;
    s32 *p;
    s32 *out;
    u32 bits;
    s32 base;
    s32 half;
    bits = x * 8;
    base = *p;
    half = (s32) (bits + (bits >> 31)) >> 1;
    *out = (s32) (base + half);
}"""


def test_combines_load_and_truncation_in_store_order():
    [(family, child)] = variants(SOURCE, 'f')
    assert family == FAMILY
    assert '*out = *p + ((s32)(x * 8) / 2);' in child
    assert 'bits =' not in child


@pytest.mark.parametrize(('old', 'new'), [
    ('bits >> 31', 'bits >> 30'), ('u32 bits;', 's32 bits;'),
    ('x * 8', 'call(x) * 8'), ('s32 *p;', 'volatile s32 *p;'),
    ('base = *p;', 'x++;\n    base = *p;'),
    ('\n}', '\n    consume(half);\n}'), ('\n}', '\n    consume(&base);\n}'),
])
def test_preserves_observable_or_unrecognised_operations(old, new):
    assert not variants(SOURCE.replace(old, new), 'f')
