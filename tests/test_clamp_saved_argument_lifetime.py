"""Match one saved register at both ends of a sampled field clamp."""

from decomprepair.clamp_saved_argument_lifetime import FAMILY, variants

SOURCE = '''
f32 sample(int, int, int);
void forward(void *, void *, f32, f32, s32, s32);
void adjust(char *record, int input)
{
    f32 result;
    f32 old;
    f32 carry;
    result = sample(input, 2, 3) * 0.2f;
    old = *((f32 *) (((char *) record) + 0x50));
    result = ((result - old) * 0.3f) + old;
    *((f32 *) (((char *) record) + 0x50)) = result;
    if (result < (-0.2f)) {
        *((f32 *) (((char *) record) + 0x50)) = -0.2f;
    } else if (result > 0.2f) {
        *((f32 *) (((char *) record) + 0x50)) = 0.2f;
    }
    result = *((f32 *) (((char *) record) + 0x50));
    forward(record, record, old, result, 0, 1);
    carry = sample(input, 0, 1);
    report(carry);
}
'''
ROWS = [
    (' ', 'addiu $a1, $zero, 2', 'addiu $a1, $zero, 2'),
    (' ', 'jal sample', 'jal sample'),
    (' ', 'addiu $a2, $zero, 3', 'addiu $a2, $zero, 3'),
    (' ', 'lui $at, 0x3e4c', 'lui $at, 0x3e4c'),
    (' ', 'ori $at, $at, 0xcccd', 'ori $at, $at, 0xcccd'),
    (' ', 'mtc1 $at, $f6', 'mtc1 $at, $f6'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f24, $f0, $f6', 'mul.s $f2, $f0, $f6'),
    (' ', 'lwc1 $f0, 0x50($s1)', 'lwc1 $f0, 0x50($s1)'),
    ('r', 'sub.s $f2, $f24, $f0', 'sub.s $f2, $f2, $f0'),
    (' ', 'nop', 'nop'),
    (' ', 'nop', 'nop'),
    (' ', 'bc1tl .Lfinish', 'bc1tl .Lfinish'),
    (' ', 'swc1 $f6, 0x50($s1)', 'swc1 $f6, 0x50($s1)'),
    ('r', 'lwc1 $f24, 0x50($s1)', 'lwc1 $f2, 0x50($s1)'),
    ('r', 'mfc1 $a3, $f24', 'mfc1 $a3, $f2'),
    (' ', 'nop', 'nop'),
    (' ', 'jal forward', 'jal forward'),
    (' ', 'move $a0, $s2', 'move $a0, $s2'),
    (' ', 'move $a1, $zero', 'move $a1, $zero'),
    (' ', 'jal sample', 'jal sample'),
    (' ', 'addiu $a2, $zero, 1', 'addiu $a2, $zero, 1'),
    (' ', 'mov.s $f24, $f0', 'mov.s $f24, $f0'),
]


def test_uses_proven_saved_local_for_scale_and_reload():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'carry = sample(input, 2, 3) * 0.2f;' in changed
    assert 'result = ((carry - old)' in changed
    assert 'forward(record, record, old, carry, 0, 1);' in changed


def test_requires_two_ends_and_donor_call_witness():
    assert not variants(SOURCE, 'adjust', ROWS[:-1])
    assert not variants(SOURCE.replace('sample(input, 0, 1)', 'sample(input, 0, 2)'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('0x50', '0x4C'), 'adjust', ROWS)


def test_does_not_replace_a_live_or_aliased_result():
    assert not variants(SOURCE.replace('report(carry);', 'report(carry, result);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report(carry);', 'report(&carry);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('forward(record, record, old,', 'forward(record, record, carry,'),
                        'adjust', ROWS)
