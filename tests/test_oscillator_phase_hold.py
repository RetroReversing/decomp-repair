from decomprepair.oscillator_phase_hold import FAMILY, variants

SOURCE = """
extern f32 phase;
extern f32 axis_z;
void update(f32 *axis_x_out, f32 *record, s32 device)
{
    f32 axis_x;
    f32 carry_x;
    f32 carry_z;
    f32 old;
    f32 sense;
    f32 filtered;
    f32 drive;
    carry_x = 0.0f;
    carry_z = 0.0f;
    drive = wave(phase);
    axis_x = wave(phase + 1.0f);
    axis_z = drive * (wave(phase) * 0.1f);
    *axis_x_out = axis_x;
    phase += 0.01f;
    carry_x += axis_x;
    sense = poll(device, 1, 2);
    old = *record;
    filtered = (((sense * 4.0f) - old) * 0.1f) + old;
    *record = filtered;
    update_position(record);
    carry_z += axis_z;
    axis_x = *record;
    report(carry_x, carry_z, axis_x);
}
"""

OPS = [
    'swc1 $f24, %lo(axis_z)($at)',
    'jal poll',
    'addiu $a2, $zero, 2',
    'mtc1 $s2, $f16',
    'nop',
    'add.s $f16, $f16, $f26',
    'mfc1 $s2, $f16',
    'mtc1 $s3, $f16',
    'nop',
    'add.s $f16, $f16, $f24',
    'mfc1 $s3, $f16',
]
ROWS = [('r', value, '') for value in OPS]


def test_uses_published_axis_and_both_accumulators_after_call():
    [(family, revised)] = variants(SOURCE, 'update', ROWS)
    assert family == FAMILY
    assert 'repair_axis_z = drive * (wave(phase) * 0.1f);' in revised
    assert 'axis_z = repair_axis_z;' in revised
    assert ('sense = poll(device, 1, 2);\n    carry_x += axis_x;\n    carry_z += repair_axis_z;\n'
            '    axis_x = sense * 4.0f;') in revised
    assert 'filtered = ((axis_x - old) * 0.1f) + old;' in revised
    assert 'carry_z += axis_z;' not in revised
    assert variants(revised, 'update', ROWS) == []


def test_checks_the_saved_value_and_existing_use_boundaries():
    different = [('r', word.replace('add.s $f16, $f16, $f24', 'add.s $f16, $f16, $f20'), '') for word in OPS]
    assert variants(SOURCE, 'update', different) == []
    assert variants(SOURCE.replace('poll(device, 1, 2)', 'poll(device, carry_x, 2)'), 'update', ROWS) == []
    assert variants(SOURCE.replace('update_position(record);', 'before(&carry_z);'), 'update', ROWS) == []
    assert variants(SOURCE.replace('axis_x = *record;', 'axis_x += *record;'), 'update', ROWS) == []
    assert variants(SOURCE, 'update', ROWS, header='#define poll(a,b,c) opaque(a,b,c)') == []
