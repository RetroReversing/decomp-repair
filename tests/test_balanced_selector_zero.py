from decomprepair import balanced_selector_zero as repair

SOURCE = '''
typedef signed char s8;
typedef signed short s16;
typedef unsigned int u32;
typedef float f32;
inline static s8 signed_field(char *data, int offset) {
    return *((s8 *) (data + offset));
}
void update(void *state, f32 initial, f32 sampled) {
    struct {
        f32 components[3];
        u32 spare[1];
    } frame;
    f32 axis;
    f32 magnitude;
    s8 old_count;
    s16 mode;
    f32 squared;
    f32 fallback_value;
    f32 saved;
    int passes;
    axis = initial;
    magnitude = sampled;
    old_count = signed_field((char *) state, 0x14);
    if (old_count != 0) {
        *((s8 *) (((char *) state) + 0x14)) = (s8) (old_count - 1);
    }
    mode = *((s16 *) (((char *) state) + 0x28));
    switch (mode) {
    case 0:
        squared = axis * axis;
        if (axis > 0.0f) {
            if (mode) {
                axis = squared * 0.25f;
            } else {
                axis = squared * 0.25f;
            }
        } else {
            axis = squared * (-0.125f);
        }
        if (probe(&frame.components[0]) <= 0.01f) {
            saved = *((f32 *) (((char *) state) + 0x24));
            passes = 1;
            fallback_value = 0.0f;
            restore(state);
            *((f32 *) (((char *) state) + 0x24)) = saved;
        } else {
            fallback_value = magnitude * 4.0f;
            if (!(magnitude > 0.0f)) {
                passes = 0;
            }
        }
        observe(axis, fallback_value);
        break;
    case 1:
        if (mode) {
            visit(state);
        } else {
            visit(state);
        }
        break;
    }
}
'''


def same(*operations):
    return [(' ', op, op) for op in operations]


COUNTDOWN = same('lb $v0, 0x14($s1)', 'beqz $v0, 0x30') + [
    ('<', 'move $v1, $v0', ''),
    ('r', 'addiu $v0, $v1, -1', 'addiu $v0, $v0, -1'),
] + same('sb $v0, 0x14($s1)', 'nop', 'nop')
SQUARE = same('bc1f .L40', 'mul.s $f2, $f26, $f26') + [('>', '', 'sll $v0, $s0, 0x10')] + same(
    'lui $at, 0x3e80', 'ori $at, $at, 0', 'mtc1 $at, $f0', 'nop',
    'j update+0x44', 'mul.s $f26, $f2, $f0',
    'lui $at, 0xbe00', 'ori $at, $at, 0', 'mtc1 $at, $f0', 'nop',
    'mul.s $f26, $f2, $f0', 'nop',
)
ZEROS = same('jal probe', 'nop', 'nop') + [
    ('|', 'mtc1 $zero, $f22', 'mov.s $f22, $f24'),
    ('o', 'nop', ''),
] + same('jal restore', *(['nop'] * 9)) + [
    ('<', 'mtc1 $zero, $f0', ''),
    ('o', 'nop', ''),
    ('r', 'c.lt.s $f0, $f30', 'c.lt.s $f24, $f30'),
] + same('nop', 'nop', 'nop')
ROWS = COUNTDOWN + SQUARE + ZEROS


def test_balances_signed_countdown_and_two_zero_materializations_through_the_same_slot():
    [(label, code)] = repair.variants(SOURCE, 'update', ROWS)
    assert label == repair.FAMILY
    assert 'if (old_count != 0)' not in code
    assert '(*((s8 *) (((char *) state) + 0x14)))--;' in code
    assert 'if (mode)' not in code
    assert 'squared = axis * axis;' not in code
    assert 'axis = (axis * axis) * 0.25f;' in code
    assert 'axis = (axis * axis) * (-0.125f);' in code
    assert 'volatile float repair_branch_zero;' in code
    assert 'fallback_value = frame.repair_branch_zero;' in code
    assert 'if (!(magnitude > frame.repair_branch_zero))' in code
    assert code.count('frame.repair_branch_zero = 0.0f;') == 2


def test_balanced_trial_requires_each_linked_witness():
    assert not repair.variants(SOURCE, 'update', SQUARE + ZEROS)
    assert not repair.variants(SOURCE, 'update', COUNTDOWN + ZEROS)
    assert not repair.variants(SOURCE, 'update', COUNTDOWN + SQUARE)


def test_balanced_trial_rejects_side_effects_and_an_observed_frame_slot():
    for source in (
        SOURCE.replace('s16 mode;', 'volatile s16 mode;'),
        SOURCE.replace('axis = squared * 0.25f;', 'axis = squared * 0.5f;', 1),
        SOURCE.replace('switch (mode) {', 'observe(frame.spare[0]);\n    switch (mode) {'),
        SOURCE.replace('switch (mode) {', 'observe(&frame);\n    switch (mode) {'),
        SOURCE.replace('} else {\n            fallback_value', '} else {\n            report(squared);\n            fallback_value'),
        SOURCE.replace('typedef unsigned int u32;', 'typedef unsigned long long u32;'),
    ):
        assert not repair.variants(source, 'update', ROWS)
