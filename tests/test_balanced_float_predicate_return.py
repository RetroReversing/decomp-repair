"""One removed delay nop can balance a witnessed saved return capture."""

from decomprepair.balanced_float_predicate_return import FAMILY, variants

SOURCE = '''
void adjust(char *record, float input)
{
    float axis;
    f32 angle_result;
    int upper;
    int lower;
    axis = input;
    upper = 1;
    if (!(axis <= 0.0002f)) {
        upper = 0;
    }
    lower = 1;
    if (!(axis >= (-0.0002f))) {
        lower = 0;
    }
    if (((lower ^ 1) | (upper ^ 1)) != 0) {
        record_event();
    }
    angle_result = next_value(input);
    *((f32 *) (((char *) record) + 0x40)) = (f32) ((*((f32 *) (((char *) record) + 0x40))) + angle_result);
    if (angle_result == 0.0f) {
        notify();
    }
}
'''
ROWS = [
    (' ', 'lui $at, 0x3951', 'lui $at, 0x3951'),
    (' ', 'ori $at, $at, 0xb717', 'ori $at, $at, 0xb717'),
    (' ', 'mtc1 $at, $f0', 'mtc1 $at, $f0'),
    (' ', 'nop', 'nop'),
    (' ', 'c.le.s $f26, $f0', 'c.le.s $f26, $f0'),
    (' ', 'nop', 'nop'),
    (' ', 'nop', 'nop'),
    (' ', 'bc1t .Lfirst', 'bc1t .Lfirst'),
    (' ', 'addiu $v1, $zero, 1', 'addiu $v1, $zero, 1'),
    (' ', 'move $v1, $zero', 'move $v1, $zero'),
    (' ', 'lui $at, 0xb951', 'lui $at, 0xb951'),
    (' ', 'ori $at, $at, 0xb717', 'ori $at, $at, 0xb717'),
    (' ', 'mtc1 $at, $f0', 'mtc1 $at, $f0'),
    (' ', 'nop', 'nop'),
    (' ', 'c.le.s $f0, $f26', 'c.le.s $f0, $f26'),
    ('o', 'addiu $v0, $zero, 1', 'nop'),
    (' ', 'nop', 'nop'),
    (' ', 'bc1t .Lsecond', 'bc1t .Lsecond'),
    ('o', '', 'addiu $v0, $zero, 1'),
    ('o', '', 'move $v0, $zero'),
    ('r', 'xori $v1, $v1, 1', 'xori $v0, $v0, 1'),
    ('o', 'move $v0, $zero', ''),
    ('r', 'xori $v0, $v0, 1', 'xori $v1, $v1, 1'),
    ('r', 'or $v0, $v1, $v0', 'or $v0, $v0, $v1'),
    (' ', 'jal next_value', 'jal next_value'),
    (' ', 'nop', 'nop'),
    ('r', 'lwc1 $f2, 0x40($s2)', 'lwc1 $f4, 0x40($s2)'),
    ('<', 'mov.s $f26, $f0', ''),
    ('r', 'add.s $f2, $f2, $f26', 'add.s $f4, $f4, $f0'),
    ('r', 'mtc1 $zero, $f0', 'mtc1 $zero, $f2'),
    (' ', 'nop', 'nop'),
    ('r', 'c.eq.s $f26, $f0', 'c.eq.s $f0, $f2'),
    (' ', 'nop', 'nop'),
    (' ', 'nop', 'nop'),
    (' ', 'bc1f .Lexit', 'bc1f .Lexit'),
    ('r', 'swc1 $f2, 0x40($s2)', 'swc1 $f4, 0x40($s2)'),
]


def test_pairs_early_predicate_stage_and_later_saved_return():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'repair_first_inverted = upper ^ 1;\n    lower = 1;' in changed
    assert '((lower ^ 1) | repair_first_inverted)' in changed
    assert 'axis = next_value(input);' in changed
    assert 'if (axis == 0.0f)' in changed


def test_requires_both_witnesses_and_matching_offset_and_threshold():
    assert not variants(SOURCE, 'adjust', ROWS[:24])
    assert not variants(SOURCE, 'adjust', ROWS[24:])
    assert not variants(SOURCE.replace('0x40', '0x44'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('0.0002f', '0.0003f'), 'adjust', ROWS)


def test_refuses_live_saved_axis_or_preexisting_probe_read():
    assert not variants(SOURCE.replace('notify();', 'notify(axis);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('next_value(input)', 'next_value(angle_result)'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('record_event();', 'record_event(&axis);'), 'adjust', ROWS)
