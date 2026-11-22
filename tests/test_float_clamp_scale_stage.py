"""Stage the measured scale before subtracting the current field."""

from decomprepair.float_clamp_scale_stage import FAMILY, variants

SOURCE = '''
void adjust(char *record)
{
    f32 axis, old, result;
    axis = sample();
    old = *((f32 *) (((char *) record) + 0x48));
    result = (((axis * 32.0f) - old) * 0.1f) + old;
    *((f32 *) (((char *) record) + 0x48)) = result;
    if (result < (-32.0f)) {
        *((f32 *) (((char *) record) + 0x48)) = -32.0f;
    }
}
'''
ROWS = [
    (' ', 'lui $at, 0x4200', 'lui $at, 0x4200'),
    (' ', 'mtc1 $at, $f6', 'mtc1 $at, $f6'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f26, $f26, $f6', 'mul.s $f0, $f22, $f6'),
    ('r', 'lwc1 $f0, 0x48($s1)', 'lwc1 $f4, 0x48($s1)'),
    ('r', 'sub.s $f2, $f26, $f0', 'sub.s $f0, $f0, $f4'),
]


def test_stages_scale_in_existing_result_without_touching_input():
    [proposal] = variants(SOURCE, 'adjust', ROWS)
    assert proposal == (
        FAMILY,
        SOURCE.replace('result = (((axis * 32.0f) - old)', 'result = axis * 32.0f;\n    result = ((result - old)'),
    )


def test_requires_matching_scale_field_and_captured_target_register():
    assert not variants(SOURCE.replace('axis * 32.0f', 'axis * 64.0f'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('0x48', '0x50'), 'adjust', ROWS)
    assert not variants(SOURCE, 'adjust', ROWS[:3] + [
        ('r', 'mul.s $f24, $f26, $f6', 'mul.s $f0, $f22, $f6')
    ] + ROWS[4:])


def test_rejects_additional_observable_local_write():
    assert not variants(SOURCE.replace('    axis =', '    use(&result);\n    axis ='), 'adjust', ROWS)
    assert not variants(SOURCE.replace('    f32 axis, old, result;',
                                       '    f32 axis, old;\n    volatile f32 result;'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('result = (((axis * 32.0f) - old)',
                                       'old = (((axis * 32.0f) - old)'), 'adjust', ROWS)
