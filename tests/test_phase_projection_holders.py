from decomprepair import phase_projection_holders as repair

SOURCE = '''
typedef float f32;

void apply_motion(void *actor, int mode, int still) {
    struct {
        f32 vector[3];
        volatile float scratch;
    } frame;
    f32 horizontal;
    f32 depth;
    f32 held;
    f32 magnitude;
    f32 gain;
    f32 center;
    f32 blended;
    f32 projected;
    f32 measured;
    f32 saved;
    f32 output;
    depth = 0.0f;
    horizontal = 0.0f;
    if (still != 0) {
        update(actor);
    }
    switch (mode) {
    case 0:
        held = sample(actor);
        magnitude = absolute(held);
        gain = 0.1f;
        center = 2.0f;
        blended = ((held - center) * gain) + center;
        projected = *((f32 *) (((char *) actor) + 12));
        if (projected < 0.2f && projected > -0.2f) {
            set_flag(actor);
        }
        horizontal = 0.0f + (projected * left_angle(actor));
        depth += (projected * right_angle(actor));
        *((f32 *) (((char *) actor) + 16)) = projected;
        measured = absolute(projected);
        if (probe(&frame.vector[0]) <= 0.01f) {
            saved = *((f32 *) (((char *) actor) + 24));
            frame.scratch = 0.0f;
            output = frame.scratch;
            restore(actor);
            *((f32 *) (((char *) actor) + 24)) = saved;
        } else {
            output = measured * 5.0f;
            frame.scratch = 0.0f;
            if (!(magnitude > frame.scratch)) {
                set_flag(actor);
            }
        }
        held = sample(actor);
        gain = 0.2f;
        use_values(held, gain, output, blended, horizontal);
        break;
    }
}
'''


def same(*instructions):
    return [(' ', op, op) for op in instructions]


ROWS = same('mul.s $f2, $f2, $f24') + [
    ('r', 'lwc1 $f26, 0xc($s1)', 'lwc1 $f20, 0xc($s1)'),
] + same('jal left_angle', 'nop') + [
    ('r', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f20, $f0'),
    ('r', 'mtc1 $s5, $f16', 'mtc1 $zero, $f24'),
] + same('jal right_angle', 'nop') + [
    ('r', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f20, $f0'),
] + same('jal absolute', 'nop') + [
    ('r', 'mov.s $f24, $f0', 'mov.s $f20, $f0'),
] + same('jal probe', *(['nop'] * 42)) + [
    ('|', 'mtc1 $zero, $f22', 'swc1 $f24, 0x24($sp)'),
    ('o', 'nop', 'lwc1 $f22, 0x24($sp)'),
] + same('jal restore', *(['nop'] * 20)) + [
    ('|', 'mtc1 $zero, $f0', 'swc1 $f24, 0x24($sp)'),
    ('o', 'nop', 'lwc1 $f0, 0x24($sp)'),
] + same('c.lt.s $f0, $f30')


def test_reuses_dead_float_holders_and_restores_both_literal_zero_uses():
    [(label, normal), (deferred, continued)] = repair.variants(SOURCE, 'apply_motion', ROWS)
    assert label == repair.FAMILY
    assert deferred == repair.DEFERRED
    assert 'horizontal += (held * left_angle(actor));' in normal
    assert 'depth += (held * right_angle(actor));' in normal
    assert 'gain = absolute(held);' in normal
    assert 'output = gain * 5.0f;' in normal
    assert 'output = 0.0f;' in normal
    assert 'if (!(magnitude > 0.0f))' in normal
    assert 'volatile float scratch;' in normal
    assert 'frame.scratch' not in normal
    assert normal.index('horizontal = 0.0f;') < normal.index('if (still != 0)')
    assert continued.index('horizontal = 0.0f;') > continued.index('update(actor);')


def test_requires_related_projections_gain_and_both_zero_sequences():
    for rows in (ROWS[1:], ROWS[:-2], ROWS[:5] + ROWS[6:],
                 [*ROWS[:1], ('r', ROWS[1][1], 'lwc1 $f20, 0x10($s1)'), *ROWS[2:]]):
        assert repair.variants(SOURCE, 'apply_motion', rows) == []


def test_rejects_observed_storage_or_a_holder_live_after_the_new_assignment():
    for source in (
        SOURCE.replace('update(actor);', 'observe(&frame);'),
        SOURCE.replace('+ 12));', '+ 28));'),
        SOURCE.replace('if (probe(', 'if (different_probe('),
        SOURCE.replace('held = sample(actor);\n        gain = 0.2f;', 'observe(held);\n        gain = 0.2f;'),
        SOURCE.replace('gain = 0.2f;', 'observe(gain);\n        gain = 0.2f;'),
        SOURCE.replace('restore(actor);', 'restore(actor);\n            observe(gain);'),
        SOURCE.replace('frame.scratch = 0.0f;', 'frame.scratch = 0.0f;\n            observe(measured);', 1),
        SOURCE.replace('horizontal = 0.0f;\n    if', 'horizontal = -0.0f;\n    if', 1),
        SOURCE.replace('    f32 projected;', '    volatile f32 projected;'),
        SOURCE.replace('output = measured * 5.0f;', 'output = measured * 5.0f;\n            observe(measured);'),
        SOURCE.replace('output = measured * 5.0f;', 'output = measured * 5.0f;\n            observe(&held);'),
    ):
        assert repair.variants(source, 'apply_motion', ROWS) == []


def test_requires_ordinary_float_types_and_a_candidate_within_the_source_limit():
    assert repair.variants(SOURCE, 'apply_motion', ROWS, header='#define f32 double') == []
    assert repair.variants(SOURCE, 'apply_motion', ROWS, max_bytes=90) == []
