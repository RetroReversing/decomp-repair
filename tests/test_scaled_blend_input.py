"""Use the saved product for signed and sampled input blends."""

from decomprepair.scaled_blend_input import FAMILY, variants

SOURCE = """\
extern f32 phase;
f32 sample(s32 port, s32 x, s32 y);
void update(char *record, s32 port, s32 input)
{
    f32 holder;
    f32 current_x;
    f32 current_y;
    f32 next_x;
    f32 next_y;
    f32 sampled;
    s32 step;
    holder = *((f32 *) (((char *) record) + 0x20));
    phase -= holder;
    step = input;
    current_x = *((f32 *) (((char *) record) + 0x14));
    next_x = (((((f32) step) * 0.25f) - current_x) * 0.25f) + current_x;
    sampled = sample(port, 2, 3);
    current_y = *((f32 *) (((char *) record) + 0x18));
    next_y = (((sampled * 0.25f) - current_y) * 0.25f) + current_y;
    report(next_x, next_y);
}
"""

DONOR = [(' ', op, op) for op in [
    'lwc1 $f26, 0x20($s0)', 'lui $at, %hi(phase)', 'lwc1 $f0, %lo(phase)($at)', 'sub.s $f0, $f0, $f26',
]]
FACTOR = [(' ', op, op) for op in ['lui $at, 0x3e80', 'ori $at, $at, 0', 'mtc1 $at, $f4']]
TAIL = [(' ', op, op) for op in ['mul.s $f0, $f0, $f4', 'add.s $f0, $f0, $f2']]
CAST = FACTOR + [
    ('r', 'mtc1 $s0, $f26', 'mtc1 $s0, $f0'),
    (' ', 'nop', 'nop'),
    ('r', 'cvt.s.w $f26, $f26', 'cvt.s.w $f0, $f0'),
    ('r', 'mul.s $f26, $f26, $f4', 'mul.s $f0, $f0, $f4'),
    (' ', 'lwc1 $f2, 0x14($s0)', 'lwc1 $f2, 0x14($s0)'),
    ('r', 'sub.s $f0, $f26, $f2', 'sub.s $f0, $f0, $f2'),
] + TAIL
SAMPLE = [(' ', op, op) for op in ['jal sample', 'addiu $a2, $zero, 3']] + FACTOR + [
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f26, $f0, $f4', 'mul.s $f0, $f0, $f4'),
    (' ', 'lwc1 $f2, 0x18($s0)', 'lwc1 $f2, 0x18($s0)'),
    ('r', 'sub.s $f0, $f26, $f2', 'sub.s $f0, $f0, $f2'),
] + TAIL
ROWS = DONOR + CAST + SAMPLE


def test_holds_the_explicit_conversion_and_sample_in_one_witnessed_local():
    [(label, candidate)] = variants(SOURCE, 'update', ROWS)
    assert label == FAMILY
    assert 'holder = (f32) step;\n    holder *= 0.25f;' in candidate
    assert 'holder = (sampled * 0.25f);' in candidate
    assert 'next_x = ((holder - current_x) * 0.25f) + current_x;' in candidate
    assert 'next_y = ((holder - current_y) * 0.25f) + current_y;' in candidate


def test_requires_the_saved_load_and_disjoint_ordinary_local():
    assert not variants(SOURCE, 'update', CAST + SAMPLE)
    assert not variants(SOURCE.replace('report(next_x, next_y);', 'report(holder);'), 'update', ROWS)
    assert not variants(SOURCE.replace('step = input;', 'send(&holder);\n    step = input;'), 'update', ROWS)
    assert not variants(SOURCE.replace('0x14', '0x1c'), 'update', ROWS)
    assert not variants(SOURCE.replace('sampled = sample(', 'sampled = other('), 'update', ROWS)
    assert not variants(SOURCE.replace('s32 step;', 'volatile s32 step;'), 'update', ROWS)
