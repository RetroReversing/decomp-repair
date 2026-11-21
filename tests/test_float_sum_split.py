"""A float field advanced by a call's result: proposals only, nothing is compiled here."""
from decomprepair.float_sum_split import variants

HEADER = 's32 angleDelta12();\n'
RAW = HEADER + '''void f(void *arg0, s32 arg1, f32 arg2) {
    M2C_FIELD(arg0, f32 *, 0x40) = (angleDelta12((s32) M2C_FIELD(arg0, f32 *, 0x40)) * (f32) arg2) + M2C_FIELD(arg0, f32 *, 0x40);
}
'''
# What the judge called 0 (score 10 -> 0 on a KMC GCC 2.7.2 angle-step function).
MATCHED = '''    s32 d_split; f32 v_split; f32 t_split;
    d_split = angleDelta12((s32) M2C_FIELD(arg0, f32 *, 0x40));
    do { t_split = d_split * (f32) arg2; } while (0);
    v_split = M2C_FIELD(arg0, f32 *, 0x40);
    M2C_FIELD(arg0, f32 *, 0x40) = v_split + t_split;
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_matched_shape_is_proposed_from_m2c_output():
    out = [src for fam, src in variants(RAW, 'f') if fam == 'float_sum_split']
    assert len(out) == 3
    assert any(_squash(MATCHED) in _squash(src) for src in out)
    assert any('do {' not in src for src in out)


def test_field_first_and_printed_dialect_are_found():
    src = RAW.replace('(angleDelta12((s32) M2C_FIELD(arg0, f32 *, 0x40)) * (f32) arg2) + M2C_FIELD(arg0, f32 *, 0x40)',
                      'M2C_FIELD(arg0, f32 *, 0x40) + arg2 * angleDelta12((s32) M2C_FIELD(arg0, f32 *, 0x40))')
    assert variants(src, 'f')
    printed = HEADER + ('void f(void *arg0, s32 arg1, f32 arg2) {\n    *((f32 *) (((char *) arg0) + 64)) = '
                        '*((f32 *) (((char *) arg0) + 64)) + (angleDelta12((s32) *((f32 *) (((char *) arg0) + 64))) * arg2);\n}\n')
    assert variants(printed, 'f')


def test_other_shapes_are_left_alone():
    assert not variants(RAW, 'f', arch='ppc')
    assert not variants(RAW.replace('f32 *', 's32 *'), 'f')                      # not a float field
    assert not variants(RAW.replace(' + M2C_FIELD(arg0, f32 *, 0x40);', ' + M2C_FIELD(arg0, f32 *, 0x44);'), 'f')
    assert not variants(RAW.replace('angleDelta12((s32) M2C_FIELD(arg0, f32 *, 0x40))', '3'), 'f')   # no call

def test_captures_the_initial_read_in_a_single_statement_wrapper():
    [fixed] = [src for _, src in variants(RAW, 'f') if ' += ' in src]
    assert 'f32 v_split = M2C_FIELD(arg0, f32 *, 0x40);' in fixed
    assert 'do { t_split = (angleDelta12((s32) v_split) * (f32) arg2); } while (0);' in fixed
    assert 'M2C_FIELD(arg0, f32 *, 0x40) += t_split;' in fixed
    extra = RAW.replace('    M2C_FIELD', '    touch();\n    M2C_FIELD', 1)
    assert not any(' += ' in src for _, src in variants(extra, 'f'))
