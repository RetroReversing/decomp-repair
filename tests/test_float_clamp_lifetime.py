from decomprepair.mips_float_local_reuse import variants

ASSEMBLY = 'div.s $f4, $f2, $f0\nc.lt.s $f4, $f6\nc.lt.s $f2, $f4'
SOURCE = """
float f(float x, float y, int enabled) {
    float value, rest;
    if (enabled) {
        value = x / y;
        if (value < -1.0f) value = -1.0f;
        else if (value > 1.0f) value = 1.0f;
        return value * x;
    }
    value = x + y;
    return value;
}
"""


def test_splits_clamped_float_without_renaming_the_later_lifetime():
    [(family, result)] = variants(SOURCE, 'f', ASSEMBLY)
    assert family == 'split_float_clamp_lifetime'
    assert 'float __repair_clamped_float = x / y;' in result
    assert 'return __repair_clamped_float * x;' in result
    assert 'value = x + y;' in result


def test_keeps_values_that_escape_or_are_live_after_the_clamp():
    assert not variants(SOURCE.replace('return value * x;', 'consume(&value);'), 'f', ASSEMBLY)
    assert not variants(SOURCE.replace('return value * x;', 'goto join;')
                        .replace('    return value;', 'join: return value;'), 'f', ASSEMBLY)
    assert not variants(SOURCE, 'f', 'mul.s $f4, $f2, $f0')
