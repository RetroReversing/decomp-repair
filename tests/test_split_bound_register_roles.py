"""Two branch stores recover the scratch register roles of a range clamp."""

from decomprepair.balanced_clamp_predicates import REGISTER_CLAMP, split_register_variants

SOURCE = """\
void bound(char *record)
{
    float saved;
    float current;
    saved = 0.25f;
    current = *((f32 *) (((char *) record) + 0x24));
    if ((current < 0.25f) || ((saved = 0.75f, current > 0.75f))) {
        *((f32 *) (((char *) record) + 0x24)) = saved;
    }
}
"""


def scratch_range(value, limit):
    return [
        'lui $at, 0x3e80', 'ori $at, $at, 0', f'mtc1 $at, {limit}',
        f'lwc1 {value}, 0x24($s1)', f'c.lt.s {value}, {limit}', 'nop', 'nop',
        'bc1tl .Llow', f'swc1 {limit}, 0x24($s1)', 'lui $at, 0x3f40', 'ori $at, $at, 0',
        f'mtc1 $at, {limit}', 'nop', f'c.lt.s {limit}, {value}', 'nop', 'nop',
        'bc1f .Lskip', 'move $a0, $s1', f'swc1 {limit}, 0x24($s1)',
    ]


ROWS = [(' ' if left == right else 'r', left, right)
        for left, right in zip(scratch_range('$f0', '$f2'), scratch_range('$f2', '$f0'))]


def test_split_retains_load_and_writes_one_bound():
    [(label, changed)] = split_register_variants(SOURCE, 'bound', ROWS)
    assert label == REGISTER_CLAMP
    assert 'current = *((f32 *) (((char *) record) + 0x24));' in changed
    assert 'if (current < 0.25f) {' in changed
    assert 'if (current > 0.75f) {' in changed
    assert '= 0.25f;' in changed and '= 0.75f;' in changed
    assert 'saved =' not in changed


def test_requires_the_same_bits_field_and_complete_register_swap():
    assert not split_register_variants(SOURCE, 'bound', ROWS[:-1])
    assert not split_register_variants(SOURCE, 'bound', [(' ', left, left) for _, left, _ in ROWS])
    assert not split_register_variants(SOURCE.replace('0.75f', '0.5f'), 'bound', ROWS)
    assert not split_register_variants(SOURCE.replace('0x24', '0x28', 1), 'bound', ROWS)
    assert not split_register_variants(SOURCE.replace('0x24', '0x28'), 'bound', ROWS)


def test_rejects_observable_or_unsafe_bound_assignments():
    assert not split_register_variants(SOURCE.replace('    saved =', '    if (enabled)\n    saved ='),
                                       'bound', ROWS)
    extra_read = SOURCE.replace('    if ((current', '    use(saved);\n    if ((current')
    assert not split_register_variants(extra_read, 'bound', ROWS)
    assert not split_register_variants(SOURCE, 'bound', ROWS, header='#define saved global_value')
