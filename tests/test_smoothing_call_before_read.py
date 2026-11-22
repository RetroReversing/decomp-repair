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


RECORD_SOURCE = '''
float cosine(float angle);
void adjust(void *object, float phase)
{
    void *record;
    float z;
    z = 0.0f;
    record = *((void **) (((char *) object) + 20));
    z += phase * cosine(*((float *) (((char *) object) + 8)));
    if (!((*((unsigned short *) (((char *) record) + 4))) & 0x20)) {
        emit(z);
    }
}
'''
RECORD_ROWS = [
    (' ', 'lwc1 $f12, 8($s2)', 'lwc1 $f12, 8($s2)'),
    ('>', '', 'lw $s0, 20($s2)'),
    (' ', 'nop', 'nop'),
    (' ', 'jal cosine', 'jal cosine'),
    (' ', 'nop', 'nop'),
    (' ', 'nop', 'nop'),
    (' ', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f26, $f0'),
    ('<', 'lw $a0, 20($s2)', ''),
    (' ', 'mtc1 $s6, $f16', 'mtc1 $s6, $f16'),
    ('r', 'lhu $v0, 4($a0)', 'lhu $v0, 4($s0)'),
    (' ', 'add.s $f16, $f16, $f0', 'add.s $f16, $f16, $f0'),
    (' ', 'andi $v0, $v0, 0x20', 'andi $v0, $v0, 0x20'),
    (' ', 'mfc1 $s6, $f16', 'mfc1 $s6, $f16'),
    (' ', 'nop', 'nop'),
]


def test_reads_the_guard_record_after_the_matching_projection():
    from decomprepair.smoothing_call_before_read import RECORD

    [(family, changed)] = variants(RECORD_SOURCE, 'adjust', RECORD_ROWS)
    assert family == RECORD
    assert changed.index('z += phase * cosine') < changed.index('record = *((void **)')
    assert changed.index('record = *((void **)') < changed.index('if (!')


def test_requires_the_late_read_and_its_consumer_and_an_unescaped_record():
    assert not variants(RECORD_SOURCE, 'adjust', RECORD_ROWS[2:])
    assert not variants(RECORD_SOURCE, 'adjust', RECORD_ROWS[:8])
    assert not variants(RECORD_SOURCE.replace('0x20', '0x40'), 'adjust', RECORD_ROWS)
    assert not variants(RECORD_SOURCE.replace('object) + 20', 'object) + 24'), 'adjust', RECORD_ROWS)
    assert not variants(RECORD_SOURCE.replace('record = *((void **)', 'register_slot(&record);\n    record = *((void **)'),
                        'adjust', RECORD_ROWS)
    assert not variants(RECORD_SOURCE.replace('object) + 8', 'record) + 8'), 'adjust', RECORD_ROWS)
