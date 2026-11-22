from decomprepair.measured_magnitude_conversion import variants

SOURCE = '''extern f64 limit;
typedef struct { float field_14; float field_1C; } __repair_record_arg;
f32 sample(void *arg, s32 steps) {
    f32 old;
    f32 magnitude;
    f32 phase;
    phase = (f32)steps;
    old = phase;
    ((__repair_record_arg*)arg)->field_14 = phase;
    if (phase < 0.0f) {
        magnitude = -phase;
    }
    return ((__repair_record_arg*)arg)->field_1C * (f32) ((f64) magnitude - limit);
}
'''
T = ['c.lt.s $f2, $f0', 'mov.s $f4, $f2', 'nop', 'bc1f .L6c', 'swc1 $f2, 0x14($a0)',
     'neg.s $f4, $f2', 'lui $at, %hi(limit)', 'ldc1 $f0, %lo(limit)($at)', 'cvt.d.s $f2, $f4',
     'sub.d $f2, $f2, $f0', 'lwc1 $f0, 0x1c($a0)', 'cvt.s.d $f2, $f2']
C = ['c.lt.s $f2, $f0', 'nop', 'nop', 'bc1f .L6c', 'swc1 $f2, 0x14($a0)', 'neg.s $f6, $f2']
ROWS = [('r', T[i], C[i] if i < len(C) else '') for i in range(len(T))]


def test_initializes_both_paths_and_stages_conversion():
    result = variants(SOURCE, 'sample', '', ROWS)
    assert len(result) == 1
    assert 'magnitude = phase;' in result[0][1]
    assert 'phase = (f32) ((f64) magnitude - limit);' in result[0][1]
    assert 'return ((__repair_record_arg*)arg)->field_1C * phase;' in result[0][1]


def test_requires_evidence_and_unshared_locals():
    assert not variants(SOURCE, 'sample', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('return ((', 'use(old); return (('), 'sample', '', ROWS)
    assert not variants(SOURCE.replace('f32 magnitude;', 'volatile f32 magnitude;'), 'sample', '', ROWS)
    assert not variants(SOURCE.replace('field_1C *', 'field_20 *'), 'sample', '', ROWS)
