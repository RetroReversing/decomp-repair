"""Reuse the guarded field local for a sampled phase with a witnessed scale."""

from decomprepair.sampled_phase_axis_stage import FAMILY, variants

SOURCE = '''
f32 sample(int, int, int);
void adjust(char *record, int input)
{
    f32 carry;
    f32 axis;
    f32 old;
    f32 result;
    int quiet;
    carry = *((f32 *) (((char *) record) + 0x50));
    quiet = 1;
    if (!(carry <= 0.0002f)) {
        quiet = 0;
    }
    if (!quiet) {
        *((f32 *) (((char *) record) + 0x34)) = carry;
    }
    axis = -sample(input, 4, 5);
    if (axis <= 0.0002f) {
        axis = sample(input, 2, 3);
    }
    scale_here:
    old = *((f32 *) (((char *) record) + 0x48));
    result = axis * 32.0f;
    result = ((result - old) * 0.1f) + old;
    report(result);
}
'''
ROWS = [
    ('r', 'lwc1 $f22, 0x50($s1)', 'lwc1 $f2, 0x50($s1)'),
    ('r', 'c.le.s $f22, $f2', 'c.le.s $f2, $f4'),
    ('r', 'swc1 $f22, 0x34($s1)', 'swc1 $f2, 0x34($s1)'),
    (' ', 'addiu $a1, $zero, 4', 'addiu $a1, $zero, 4'),
    (' ', 'jal sample', 'jal sample'),
    (' ', 'addiu $a2, $zero, 5', 'addiu $a2, $zero, 5'),
    ('r', 'neg.s $f26, $f0', 'neg.s $f22, $f0'),
    (' ', 'lui $at, 0x4200', 'lui $at, 0x4200'),
    (' ', 'mtc1 $at, $f6', 'mtc1 $at, $f6'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f26, $f26, $f6', 'mul.s $f2, $f22, $f6'),
    (' ', 'lwc1 $f0, 0x48($s1)', 'lwc1 $f0, 0x48($s1)'),
    ('r', 'sub.s $f2, $f26, $f0', 'sub.s $f2, $f2, $f0'),
]


def test_reuses_guarded_field_local_and_scales_it_in_place():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'carry = -sample(input, 4, 5);' in changed
    assert 'carry = sample(input, 2, 3);' in changed
    assert 'carry *= 32.0f;' in changed and 'result = ((carry - old)' in changed


def test_requires_both_lifetimes_and_the_exact_scale():
    assert not variants(SOURCE, 'adjust', ROWS[3:])
    assert not variants(SOURCE, 'adjust', ROWS[:7])
    assert not variants(SOURCE.replace('32.0f', '64.0f'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('input, 4, 5', 'input, 6, 7'), 'adjust', ROWS)


def test_refuses_unchecked_entry_or_live_source_values():
    enters_late = SOURCE.replace('axis = -sample', 'if (input) goto scale_here;\n    axis = -sample')
    assert not variants(enters_late, 'adjust', ROWS)
    assert not variants(SOURCE.replace('report(result);', 'report(result, carry);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report(result);', 'report(result, axis);'), 'adjust', ROWS)
