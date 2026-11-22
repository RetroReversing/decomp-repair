from decomprepair.oscillator_phase_hold import FAMILY, PRODUCT, product_variants, variants

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


PRODUCT_SOURCE = """\
extern f32 phase;
extern f32 axis_z;
f32 wave(f32 phase);
f32 poll(s32 slot, s32 x, s32 y);
void update(f32 *axis_x_out, s32 slot)
{
    f32 holder;
    f32 axis_x;
    f32 input;
    f32 carry_x;
    f32 carry_z;
    f32 product;
    f32 drive;
    drive = wave(phase);
    axis_x = wave(phase + 1.0f);
    carry_x = 0.0f;
    carry_z = 0.0f;
    product = drive * (wave(phase * 3.0f) * 0.1f);
    axis_z = product;
    *axis_x_out = axis_x;
    phase += 0.01f;
    input = poll(slot, 4, 5);
    carry_x += axis_x;
    carry_z += product;
    report(carry_x, carry_z, input);
    holder = poll(slot, 2, 3) * 0.5f;
    report(holder);
}
"""
PRODUCT_OPS = [
    'jal wave', 'nop', 'mul.s $f0, $f0, $f22', 'mul.s $f24, $f20, $f0',
    'swc1 $f24, %lo(axis_z)($at)', 'jal poll', 'addiu $a2, $zero, 5',
    'mtc1 $s2, $f16', 'nop', 'add.s $f16, $f16, $f24', 'mfc1 $s2, $f16',
]
PRODUCT_ROWS = [('r' if '$f24' in op else ' ', op, op.replace('$f24', '$f20')) for op in PRODUCT_OPS]
PRODUCT_ROWS += [(' ', op, op) for op in [
    'addiu $a1, $zero, 2', 'jal poll', 'addiu $a2, $zero, 3',
    'lui $at, 0x3f00', 'ori $at, $at, 0', 'mtc1 $at, $f6', 'nop',
    'mul.s $f24, $f0, $f6', *(['nop'] * 10),
]]


def test_reuses_saved_product_for_the_global_and_later_accumulation():
    [(label, changed)] = product_variants(PRODUCT_SOURCE, 'update', PRODUCT_ROWS)
    assert label == PRODUCT
    assert 'holder = drive * (wave(phase * 3.0f) * 0.1f);' in changed
    assert 'axis_z = holder;' in changed
    assert 'carry_z += holder;' in changed


def test_rejects_missing_store_witness_unproved_holder_or_escaping_product():
    incomplete = [row for row in PRODUCT_ROWS if 'swc1' not in row[1]]
    assert not product_variants(PRODUCT_SOURCE, 'update', incomplete)
    assert not product_variants(PRODUCT_SOURCE.replace(' * 0.5f;', ' * 0.25f;'), 'update', PRODUCT_ROWS)
    escaped = PRODUCT_SOURCE.replace('report(carry_x, carry_z, input);', 'escape(&product);')
    assert not product_variants(escaped, 'update', PRODUCT_ROWS)
    used = PRODUCT_SOURCE.replace('report(carry_x, carry_z, input);', 'report(holder);')
    assert not product_variants(used, 'update', PRODUCT_ROWS)
