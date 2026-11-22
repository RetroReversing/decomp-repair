import struct

from decomprepair.unsigned_float_bias import variants

SOURCE = """
void decode(u32 *data, f32 *out, int base, int i, int count) {
    int index;
    index = base;
    do {
        do {
            u32 word = data[base + i];
            out[0] = (f32)((f64)((word >> 22) * 4U));
            out[1] = (f32)((f64)((word >> 10) & 0xffeU));
            out[2] = (f32)((f64)((word << 1) & 0xffeU));
        } while (++i < count);
    } while (0);
}
"""
POOL = ('i', 'ldc1 $f20, %lo(conversionBias)($at)', 'ldc1 $f20, %lo(?local)($at)')
CONVERSION = [(' ', line, line) for line in (
    'cvt.d.w $f0, $f0', 'bltzl $v0, 0x48', 'add.d $f0, $f0, $f20', 'cvt.s.d $f0, $f0'
)]
ROWS = [POOL, *CONVERSION * 3]


def read_bias(symbol, width):
    return struct.pack('>d', 4294967296.0) if (symbol, width) == ('conversionBias', 8) else None


def test_bind_verified_unsigned_conversion_bias():
    [(label, source)] = variants(SOURCE, 'decode', '', ROWS, read_bias, True)
    assert label == 'unsigned_float_bias'
    assert 'extern const f64 conversionBias;' in source
    assert 'f64 repair_conversion_bias = conversionBias;\n    index = base;' in source
    assert source.count('repair_unsigned_float(') == 4
    assert 'repair_unsigned_float((word << 1) & 0xffeU, repair_conversion_bias)' in source


def test_reject_wrong_bias_and_different_conversion():
    assert not variants(SOURCE, 'decode', '', ROWS, read_bias, False)
    assert not variants(SOURCE, 'decode', '', ROWS[:-1], read_bias, True)
    assert not variants(SOURCE, 'decode', '', ROWS[1:], read_bias, True)
    assert not variants(SOURCE.replace('(word << 1)', '(other << 1)'), 'decode', '', ROWS, read_bias, True)
    assert not variants(SOURCE, 'decode', '#define u32 long', ROWS, read_bias, True)
