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


def test_reloaded_axis_can_hold_a_scale_with_both_literal_words():
    from decomprepair.float_clamp_scale_stage import IN_PLACE

    helper = 'static inline f32 *field(void *base) {\n    return (f32 *) (((char *) base) + 0x48);\n}\n'
    source = helper + SOURCE.replace('old = *((f32 *) (((char *) record) + 0x48))', 'old = *field(record)')
    source = source.replace('axis * 32.0f', 'axis * 0.12f')
    source = source[:source.rindex('}')] + '''
    else if (result > 32.0f) {
        *field(record) = 32.0f;
    }
    axis = *field(record);
    report(axis);
}
'''
    rows = [(' ', 'lui $at, 0x3df5', 'lui $at, 0x3df5'),
            (' ', 'ori $at, $at, 0xc28f', 'ori $at, $at, 0xc28f')] + ROWS[1:]
    [candidate] = [text for family, text in variants(source, 'adjust', rows) if family == IN_PLACE]
    assert 'axis = axis * 0.12f;\n    old = *field(record);' in candidate
    assert 'result = ((axis - old)' in candidate

    for changed in (
        source.replace('axis = *field(record);', 'report(axis);\n    axis = *field(record);'),
        source.replace('axis = *field(record);', 'axis = *field(other);'),
        source.replace('*field(record) = 32.0f;', '*field(other) = 32.0f;'),
        source.replace('axis * 0.12f', 'axis * 0.13f'),
    ):
        assert all(family != IN_PLACE for family, _ in variants(changed, 'adjust', rows))


def test_pairs_signed_square_capture_and_in_place_scale_before_reload():
    from decomprepair.float_clamp_scale_stage import SIGNED_SQUARE

    sign = '''    original = axis;
    axis = axis * axis;
    if (original < 0.0f) {
        axis = -axis;
    }
'''
    source = SOURCE.replace('f32 axis,', 'f32 original, axis,').replace('    old =', sign + '    old =')
    source = source[:source.rindex('}')] + '''
    else if (result > 32.0f) {
        *((f32 *) (((char *) record) + 0x48)) = 32.0f;
    }
    axis = *((f32 *) (((char *) record) + 0x48));
    report(axis, result);
}
'''
    prefix = [
        (' ', 'jal sample', 'jal sample'),
        (' ', 'nop', 'nop'),
        (' ', 'mov.s $f26, $f0', 'mov.s $f26, $f0'),
        ('r', 'mtc1 $zero, $f0', 'mtc1 $zero, $f2'),
        ('o', 'mov.s $f24, $f26', 'nop'),
        ('r', 'c.lt.s $f24, $f0', 'c.lt.s $f0, $f2'),
        (' ', 'nop', 'nop'),
        (' ', 'nop', 'nop'),
        (' ', 'bc1f .Lpositive', 'bc1f .Lpositive'),
        (' ', 'mul.s $f26, $f26, $f26', 'mul.s $f26, $f26, $f26'),
        (' ', 'neg.s $f26, $f26', 'neg.s $f26, $f26'),
    ]

    def candidates(code, rows):
        return [text for family, text in variants(code, 'adjust', rows) if family == SIGNED_SQUARE]

    [changed] = candidates(source, prefix + ROWS)
    assert 'result = axis;\n    axis = axis * axis;' in changed
    assert 'if (result < 0.0f)' in changed
    assert 'axis *= 32.0f;\n    old =' in changed
    assert 'result = ((axis - old)' in changed
    assert not candidates(source, ROWS)
    assert not candidates(source.replace('report(axis, result);', 'report(axis, original);'), prefix + ROWS)
    assert not candidates(source.replace('    axis = *((', '    inspect(axis);\n    axis = *(('), prefix + ROWS)
    assert not candidates(source.replace('    axis = sample();', '    escape(&result);\n    axis = sample();'),
                          prefix + ROWS)

    restored = source.replace(
        '    axis = *((f32 *) (((char *) record) + 0x48));',
        '    { f32 capture = axis;\n'
        '      axis = *((f32 *) (((char *) record) + 0x48));\n'
        '      total -= axis;\n'
        '      axis = capture; }\n'
        '    axis = next_sample(record);',
    )
    assert candidates(restored, prefix + ROWS)
    assert not candidates(restored.replace('next_sample(record)', 'next_sample(axis)'), prefix + ROWS)
