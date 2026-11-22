"""Keep the sign in a witnessed dead local while squaring a sampled axis."""

from decomprepair.quadratic_sign_holder import FAMILY, variants

SOURCE = """\
float sample(int port, int x, int y);
void track(int port, int mode)
{
    float axis;
    float scratch;
    float held;
    if (mode) {
        axis = sample(port, 4, 5);
        scratch = axis;
        axis = (axis * axis) * 2.5f;
        if (scratch < 0.0f) {
            axis = -axis;
        }
        record(axis);
    } else {
        held = sample(port, 2, 3) * 0.5f;
        record(held);
    }
}
"""

DEMAND = [
    'addiu $a1, $zero, 4', 'jal sample', 'addiu $a2, $zero, 5',
    'mov.s $f26, $f0', 'mul.s $f2, $f26, $f26', 'mov.s $f24, $f26', 'mtc1 $zero, $f0',
    'lui $at, 0x4020', 'ori $at, $at, 0', 'mtc1 $at, $f6', 'c.lt.s $f24, $f0',
    'nop', 'nop', 'bc1f .Lkeep', 'mul.s $f26, $f2, $f6', 'neg.s $f26, $f26', 'nop',
]
DONOR = [
    'addiu $a1, $zero, 2', 'jal sample', 'addiu $a2, $zero, 3',
    'lui $at, 0x3f00', 'ori $at, $at, 0', 'mtc1 $at, $f6', 'nop',
    'mul.s $f24, $f0, $f6', 'nop', 'nop', 'nop', 'nop', 'nop', 'nop', 'nop', 'nop', 'nop',
]
ROWS = [(' ' if '$f24' not in op else 'r', op, op.replace('$f24', '$f2')) for op in DEMAND]
ROWS += [(' ', op, op) for op in DONOR]


def test_reuses_the_dead_carrier_for_assignment_and_sign_test():
    [(family, changed)] = variants(SOURCE, 'track', ROWS)
    assert family == FAMILY
    assert 'held = axis;' in changed
    assert 'if (held < 0.0f)' in changed
    assert 'axis = (axis * axis) * 2.5f;' in changed
    assert 'axis = -axis;' in changed


def test_requires_matching_selector_pairs_scale_and_saved_operand():
    assert not variants(SOURCE, 'track', ROWS[:len(DEMAND)])
    assert not variants(SOURCE.replace('port, 4, 5', 'port, 0, 1'), 'track', ROWS)
    assert not variants(SOURCE.replace('port, 2, 3', 'port, 0, 1'), 'track', ROWS)
    assert not variants(SOURCE.replace('0.5f', '0.25f'), 'track', ROWS)
    replaced = ROWS[:len(DEMAND)] + [(' ', op.replace('$f24', '$f20'), op.replace('$f24', '$f20')) for op in DONOR]
    assert not variants(SOURCE, 'track', replaced)


def test_rejects_live_or_escaping_values():
    live = SOURCE.replace('record(axis);', 'record(axis, held);')
    assert not variants(live, 'track', ROWS)
    live = SOURCE.replace('record(axis);', 'record(axis, scratch);')
    assert not variants(live, 'track', ROWS)
    escaped = SOURCE.replace('    if (mode)', '    preserve(&held);\n    if (mode)')
    assert not variants(escaped, 'track', ROWS)
    assert not variants(SOURCE, 'track', ROWS, header='#define held some_other_value')


def test_groups_both_measured_sites_and_rejects_an_ambiguous_extra_site():
    start = SOURCE.index('        axis = sample')
    end = SOURCE.index('        record(axis);')
    block = SOURCE[start:end]
    linked_twice = ROWS[:len(DEMAND)] + ROWS
    [(family, changed)] = variants(SOURCE[:end] + block + SOURCE[end:], 'track', linked_twice)
    assert family == FAMILY
    assert changed.count('if (held < 0.0f)') == 2
    assert not variants(SOURCE[:end] + block * 2 + SOURCE[end:], 'track', linked_twice)
