"""Require both witnesses before pairing a saved scale and an earlier predicate stage."""

from test_balanced_float_predicate_return import ROWS as PREDICATE_ROWS

from decomprepair.balanced_projection_scale import FAMILY, variants

SOURCE = '''
void adjust(char *record, float input)
{
    float axis;
    f32 projection;
    f32 value;
    f32 prior;
    f32 result;
    float horizontal = 0.0f;
    float vertical = 0.0f;
    int upper;
    int lower;
    axis = input;
    value = input;
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
    projection = *((f32 *) (((char *) record) + 4));
    horizontal += (projection * angle_sin(axis));
    vertical += (projection * angle_cos(axis));
    prior = *((f32 *) (((char *) record) + 8));
    result = (((value * 0.25f) - prior) * 0.05f) + prior;
    *((f32 *) (((char *) record) + 8)) = (((value * 0.25f) - prior) * 0.05f) + prior;
    report(horizontal, vertical, result);
}
'''
EARLY = PREDICATE_ROWS[:24]
LATE = [
    (' ', 'jal angle_cos', 'jal angle_cos'),
    (' ', 'add.s $f12, $f12, $f20', 'add.s $f12, $f12, $f20'),
    ('o', 'nop', ''),
    ('o', 'mul.s $f0, $f26, $f0', ''),
    (' ', 'lui $at, 0x3e80', 'lui $at, 0x3e80'),
    (' ', 'ori $at, $at, 0', 'ori $at, $at, 0'),
    (' ', 'mtc1 $at, $f8', 'mtc1 $at, $f8'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f26, $f30, $f8', 'mul.s $f2, $f30, $f8'),
    (' ', 'lwc1 $f6, 8($s1)', 'lwc1 $f6, 8($s1)'),
    ('o', '', 'mul.s $f0, $f26, $f0'),
    ('r', 'sub.s $f2, $f26, $f6', 'sub.s $f2, $f2, $f6'),
]
ROWS = EARLY + LATE


def test_pairs_scale_in_exhausted_projection_local_with_predicate_move():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'repair_guard_fold_bits = upper ^ 1;\n    lower = 1;' in changed
    assert '((lower ^ 1) | repair_guard_fold_bits)' in changed
    assert 'projection = value * 0.25f;\n    prior =' in changed
    assert changed.count('((projection - prior) * 0.05f) + prior') == 2


def test_requires_both_witnesses_and_matching_value_and_field():
    assert not variants(SOURCE, 'adjust', EARLY)
    assert not variants(SOURCE, 'adjust', LATE)
    assert not variants(SOURCE.replace('0.25f', '0.5f'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('+ 8', '+ 12'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('angle_cos', 'other'), 'adjust', ROWS)


def test_refuses_live_escaped_or_reused_holder():
    assert not variants(SOURCE.replace('report(horizontal', 'report(projection, horizontal'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('record_event();', 'record_event(&projection);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('value * 0.25f', 'projection * 0.25f'), 'adjust', ROWS)
