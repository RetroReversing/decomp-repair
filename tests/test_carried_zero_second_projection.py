"""Keep the proven zero in the second projection's incoming accumulator."""

from decomprepair.balanced_predicate_projection import SECOND, variants

SOURCE = """\
float forward(float angle);
float sideways(float angle);
void project(float sample, float angle, int mode)
{
    float axis;
    float x;
    float z;
    union { u32 bits; f32 number; } zero;
    axis = sample;
    zero.bits = 0;
    x = 0.0f;
    z = zero.number;
    if (mode) {
        x += (axis * forward(angle));
        z = 0.0f + (axis * sideways(angle));
    }
    report(x, z);
}
"""
MATCHED = [(' ', op, op) for op in [
    'jal forward', 'nop', 'mul.s $f0, $f26, $f0', 'mtc1 $s5, $f16', 'nop',
    'add.s $f16, $f16, $f0', 'lwc1 $f12, 4($s1)', 'mfc1 $s5, $f16',
]]
MISMATCHED = [
    (' ', 'jal sideways', 'jal sideways'),
    (' ', 'nop', 'nop'),
    (' ', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f26, $f0'),
    ('r', 'mtc1 $s6, $f16', 'mtc1 $zero, $f2'),
    (' ', 'nop', 'nop'),
    ('r', 'add.s $f16, $f16, $f0', 'add.s $f0, $f0, $f2'),
    ('r', 'mfc1 $s6, $f16', 'mfc1 $s6, $f0'),
]
ROWS = MATCHED + MISMATCHED


def test_carries_zero_only_through_the_second_adjacent_projection():
    [(label, changed)] = variants(SOURCE, 'project', ROWS)
    assert label == SECOND
    assert 'x += (axis * forward(angle));' in changed
    assert 'z += (axis * sideways(angle));' in changed


def test_checks_the_first_transfer_and_all_incoming_zero_paths():
    assert not variants(SOURCE, 'project', MISMATCHED)
    wrong_first = SOURCE.replace('x += (axis * forward(angle));', 'x += (axis * other(angle));')
    assert not variants(wrong_first, 'project', ROWS)
    changed_result = SOURCE.replace('    if (mode)', '    if (mode == 2) z = 1.0f;\n    if (mode)')
    assert not variants(changed_result, 'project', ROWS)
    negative_zero = SOURCE.replace('z = zero.number;', 'z = -0.0f;')
    assert not variants(negative_zero, 'project', ROWS)
    between = SOURCE.replace('        z = 0.0f', '        inspect(axis);\n        z = 0.0f')
    assert not variants(between, 'project', ROWS)
    assert not variants(SOURCE, 'project', ROWS, header='#define sideways(a) opaque(a)')
    mutating = SOURCE.replace('sideways(angle)', 'sideways((z = 3.0f, angle))')
    assert not variants(mutating, 'project', ROWS)
