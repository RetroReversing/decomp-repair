"""Keep a clamped record read in a previously allocated float register."""

from decomprepair.clamped_field_reload import FAMILY, variants

SOURCE = '''
extern f32 balance;
void adjust(char *record, f32 input)
{
    f32 axis, old, result;
    axis = input;
    old = *((f32 *) (((char *) record) + 0x48));
    result = ((axis - old) * 0.8f) + old;
    *((f32 *) (((char *) record) + 0x48)) = result;
    if (result < (-82.8f)) {
        *((f32 *) (((char *) record) + 0x48)) = -82.8f;
    } else if (result > 82.8f) {
        *((f32 *) (((char *) record) + 0x48)) = 82.8f;
    }
    balance -= *((f32 *) (((char *) record) + 0x48));
    observe(axis);
}
'''
ROWS = [
    (' ', 'bc1tl .Lfinish', 'bc1tl .Lfinish'),
    (' ', 'swc1 $f6, 0x48($s1)', 'swc1 $f6, 0x48($s1)'),
    ('<', 'lwc1 $f26, 0x48($s1)', ''),
    (' ', 'lui $at, %hi(balance)', 'lui $at, %hi(balance)'),
    (' ', 'lwc1 $f0, %lo(balance)($at)', 'lwc1 $f0, %lo(balance)($at)'),
    ('>', '', 'lwc1 $f2, 0x48($s1)'),
    ('r', 'sub.s $f0, $f0, $f26', 'sub.s $f0, $f0, $f2'),
    (' ', 'swc1 $f0, %lo(balance)($at)', 'swc1 $f0, %lo(balance)($at)'),
]


def test_reuses_saved_axis_and_restores_original_value_after_subtraction():
    [proposal] = variants(SOURCE, 'adjust', ROWS)
    assert proposal[0] == FAMILY
    assert '{ f32 repair_saved_axis = axis;' in proposal[1]
    assert 'balance -= axis;\n    axis = repair_saved_axis; }\n    observe(axis);' in proposal[1]


def test_only_matching_field_and_global_subtraction_qualify():
    assert variants(SOURCE, 'adjust', ROWS[:6]) == []
    assert variants(SOURCE.replace('0x48', '0x58'), 'adjust', ROWS) == []
    assert variants(SOURCE.replace('balance', 'weight'), 'adjust', ROWS) == []
    assert variants(SOURCE.replace('f32 balance;', 'volatile f32 balance;'), 'adjust', ROWS) == []


def test_supports_scaled_axis_and_refuses_escaped_axis():
    scaled = SOURCE.replace('((axis - old)', '(((axis * 2.5f) - old)')
    assert variants(scaled, 'adjust', ROWS)
    escaped = scaled.replace('observe(axis)', 'observe(&axis)')
    assert not variants(escaped, 'adjust', ROWS)
