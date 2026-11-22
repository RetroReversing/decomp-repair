"""Witness both branch-local uses before inlining a shared square."""

from decomprepair.quadratic_sign_holder import ARMS, arm_variants

SOURCE = """\
void respond(float input)
{
    float axis;
    float squared;
    axis = input;
    squared = axis * axis;
    if (axis > 0.0f) {
        axis = (squared * 0.25f) + 0.5f;
    } else {
        axis = (squared * (-0.125f)) - 0.5f;
    }
    transmit(axis);
}
"""
OPS = [
    'c.lt.s $f0, $f26', 'nop', 'nop', 'bc1f .Lnegative', 'mul.s $f0, $f26, $f26',
    'lui $at, 0x3e80', 'ori $at, $at, 0', 'mtc1 $at, $f2', 'nop', 'mul.s $f0, $f0, $f2',
    'lui $at, 0x3f00', 'ori $at, $at, 0', 'mtc1 $at, $f2', 'nop', 'j .Ljoin', 'add.s $f26, $f0, $f2',
    'lui $at, 0xbe00', 'ori $at, $at, 0', 'mtc1 $at, $f2', 'nop', 'mul.s $f0, $f0, $f2',
    'lui $at, 0x3f00', 'ori $at, $at, 0', 'mtc1 $at, $f2', 'nop', 'sub.s $f26, $f0, $f2',
]
SWAPS = {4: 'mul.s $f2, $f26, $f26', 7: 'mtc1 $at, $f0', 9: 'mul.s $f0, $f2, $f0',
         18: 'mtc1 $at, $f0', 20: 'mul.s $f0, $f2, $f0'}
ROWS = [('r' if i in SWAPS else ' ', op, SWAPS.get(i, op)) for i, op in enumerate(OPS)]


def test_inlines_only_the_square_and_preserves_both_factors_and_bias():
    [(label, changed)] = arm_variants(SOURCE, 'respond', ROWS)
    assert label == ARMS
    assert 'squared =' not in changed
    assert 'axis = ((axis * axis) * 0.25f) + 0.5f;' in changed
    assert 'axis = ((axis * axis) * (-0.125f)) - 0.5f;' in changed
    multiline = SOURCE.replace('squared = axis * axis;', 'squared =\n        axis * axis;')
    assert arm_variants(multiline, 'respond', ROWS) == [(ARMS, changed)]


def test_requires_the_two_arms_and_the_only_two_reads():
    assert not arm_variants(SOURCE, 'respond', ROWS[:-4])
    assert not arm_variants(SOURCE.replace(' * 0.25f)', ' * 0.75f)'), 'respond', ROWS)
    assert not arm_variants(SOURCE.replace('transmit(axis)', 'transmit(axis, squared)'), 'respond', ROWS)
    assert not arm_variants(SOURCE.replace('float axis;', 'volatile float axis;'), 'respond', ROWS)
    assert not arm_variants(SOURCE, 'respond', ROWS, header='#define squared memory_value')


def test_combines_distinct_measured_branches_and_offers_each_individually():
    start = SOURCE.index('    squared =')
    end = SOURCE.index('    transmit(axis);')
    second = SOURCE[start:end].replace('squared', 'other').replace('0.25f', '0.75f')
    source = (SOURCE[:end] + second + SOURCE[end:]).replace('float squared;', 'float squared;\n    float other;')
    different_factor = [(tag, a.replace('0x3e80', '0x3f40'), b.replace('0x3e80', '0x3f40'))
                        for tag, a, b in ROWS]
    assert [candidate.count('((axis * axis) *') for _, candidate in
            arm_variants(source, 'respond', ROWS + different_factor)] == [4, 2, 2]
