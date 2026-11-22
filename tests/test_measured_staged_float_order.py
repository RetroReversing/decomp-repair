from decomprepair.measured_staged_float_order import FAMILY, variants

SOURCE = """
static inline float sum_field(float *address, float delta) { return *address + delta; }
void f(void *base) {
    float a;
    float b;
    float c;
    float x;
    float y;
    float z;
    x = 1.0f;
    y = 2.0f;
    z = 3.0f;
    a = sum_field((float *) (((char *) base) + 0x4), x);
    b = sum_field((float *) (((char *) base) + 0x8), y);
    c = sum_field((float *) (((char *) base) + 0xC), z);
    *((float *) (((char *) base) + 0x4)) = a;
    *((float *) (((char *) base) + 0x8)) = b;
    *((float *) (((char *) base) + 0xC)) = c;
}
"""
ROWS = [('i', 'swc1 $f4, 0xc($s2)', 'swc1 $f4, 0x8($s2)')]


def test_paired_float_order_keeps_captures_ahead_of_stores():
    choices = variants(SOURCE, 'f', ROWS)
    assert len(choices) == 11
    assert all(family == FAMILY for family, _ in choices)
    for _, text in choices:
        assert text.index('c = sum_field') < text.index(' = a;')
    assert any(text.index('c = sum_field') < text.index('b = sum_field')
               and text.index(' = b;') < text.index(' = c;') < text.index(' = a;')
               for _, text in choices)


def test_rejects_aliasing_destinations_volatile_inputs_and_impure_helpers():
    for before, after in (
        ('+ 0xC', '+ 0x8'),
        ('float y;', 'volatile float y;'),
        ('void *base', 'void *volatile base'),
        ('return *address + delta;', 'return next() + *address + delta;'),
    ):
        assert not variants(SOURCE.replace(before, after), 'f', ROWS)
    assert not variants(SOURCE, 'f', [])
