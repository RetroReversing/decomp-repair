"""Reuse a verified saved register's ordinary float lifetime."""

from decomprepair.saved_range_probe import FAMILY, variants

SOURCE = '''
void adjust(char *record, f32 input)
{
    f32 saved, probe;
    int upper, lower;
    saved = *((f32 *) (((char *) record) + 0x58));
    rebuild(record);
    *((f32 *) (((char *) record) + 0x58)) = saved;
    probe = sample(input);
    upper = 1;
    if (!(probe <= 0.125f)) {
        upper = 0;
    }
    lower = 1;
    if (!(probe >= (-0.125f))) {
        lower = 0;
    }
    report(upper, lower);
}
'''
ROWS = [
    (' ', 'lwc1 $f20, 0x58($s1)', 'lwc1 $f20, 0x58($s1)'),
    (' ', 'jal rebuild', 'jal rebuild'),
    (' ', 'nop', 'nop'),
    (' ', 'swc1 $f20, 0x58($s1)', 'swc1 $f20, 0x58($s1)'),
    (' ', 'jal sample', 'jal sample'),
    (' ', 'nop', 'nop'),
    ('r', 'mov.s $f20, $f0', 'mov.s $f4, $f0'),
    ('r', 'c.le.s $f20, $f2', 'c.le.s $f4, $f2'),
    (' ', 'nop', 'nop'),
    ('r', 'c.le.s $f0, $f20', 'c.le.s $f0, $f4'),
]


def test_later_probe_reuses_completed_saved_lifetime():
    [proposal] = variants(SOURCE, 'adjust', ROWS)
    assert proposal == (
        FAMILY,
        SOURCE.replace('probe = sample(input);', 'saved = sample(input);')
        .replace('probe <=', 'saved <=').replace('probe >=', 'saved >='),
    )


def test_requires_agreement_on_earlier_saved_register_and_offset():
    assert variants(SOURCE, 'adjust', ROWS[:-1]) == []
    assert variants(SOURCE.replace('0x58', '0x5C'), 'adjust', ROWS) == []
    assert variants(SOURCE.replace('rebuild(record)', 'update(record)'), 'adjust', ROWS) == []
    wrong_register = [(flag, left.replace('$f20', '$f22'), right) for flag, left, right in ROWS[:4]] + ROWS[4:]
    assert variants(SOURCE, 'adjust', wrong_register) == []


def test_original_temporary_and_saved_value_must_be_private_to_their_lifetimes():
    for code in (
        SOURCE.replace('report(upper, lower)', 'report(upper, lower, saved)'),
        SOURCE.replace('sample(input)', 'sample(probe)'),
        SOURCE.replace('rebuild(record)', 'rebuild(record, &saved)'),
        SOURCE.replace('probe = sample(input);', 'if (input != 0.0f)\n        probe = sample(input);'),
    ):
        assert variants(code, 'adjust', ROWS) == []
