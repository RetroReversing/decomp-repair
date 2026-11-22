"""Use the observed target order for a sample and a smoothing field."""

from decomprepair.smoothing_call_before_read import FAMILY, variants

HEADER = 'f32 sample(int, int, int);\n'
SOURCE = '''
void adjust(char *record, int input)
{
    f32 old, result;
    old = *((f32 *) (((char *) record) + 0x50));
    result = (((sample(input, 2, 3) * 0.2f) - old) * 0.3f) + old;
    *((f32 *) (((char *) record) + 0x50)) = result;
    if (result < (-0.2f)) {
        *((f32 *) (((char *) record) + 0x50)) = -0.2f;
    }
}
'''
ROWS = [
    ('>', '', 'lwc1 $f20, 0x50($s1)'),
    (' ', 'jal sample', 'jal sample'),
    (' ', 'addiu $a2, $zero, 3', 'addiu $a2, $zero, 3'),
    (' ', 'lui $at, 0x3e4c', 'lui $at, 0x3e4c'),
    (' ', 'ori $at, $at, 0xcccd', 'ori $at, $at, 0xcccd'),
    ('r', 'mtc1 $at, $f6', 'mtc1 $at, $f4'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f24, $f0, $f6', 'mul.s $f0, $f0, $f4'),
    ('o', 'lwc1 $f0, 0x50($s1)', ''),
    ('r', 'sub.s $f2, $f24, $f0', 'sub.s $f0, $f0, $f20'),
]


def test_stages_scaled_call_before_loading_existing_field():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS, header=HEADER)
    assert family == FAMILY
    assert 'result = sample(input, 2, 3) * 0.2f;\n    old =' in changed
    assert 'result = ((result - old) * 0.3f) + old;' in changed


def test_requires_both_target_and_candidate_order_and_matching_immediates():
    assert not variants(SOURCE, 'adjust', ROWS[1:], header=HEADER)
    assert not variants(SOURCE, 'adjust', ROWS[:-1], header=HEADER)
    assert not variants(SOURCE.replace('0x50', '0x48'), 'adjust', ROWS, header=HEADER)
    assert not variants(SOURCE.replace('3) * 0.2f', '3) * 0.25f'), 'adjust', ROWS, header=HEADER)


def test_rejects_old_value_argument_or_observable_local_write():
    assert not variants(SOURCE.replace('sample(input', 'sample(old'), 'adjust', ROWS, header=HEADER)
    assert not variants(SOURCE.replace('f32 old, result;', 'f32 old;\n    volatile f32 result;'),
                        'adjust', ROWS, header=HEADER)
    assert not variants(SOURCE.replace('old =', 'use(&old);\n    old ='), 'adjust', ROWS, header=HEADER)
