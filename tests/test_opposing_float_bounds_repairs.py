from decomprepair import opposing_float_bounds_repairs as repair

SOURCE = """\
void f(char *range, char *actor) {
    f32 center;
    int positive;
    int upper;
    int lower;
    center = *((f32 *)(actor + 0x28));
    positive = 1;
    upper = 1;
    if (!(((*((f32 *) (((char *) range) + 0xF0))) - center) <= 1.5f)) {
        upper = 0;
    }
    if (positive & upper) {
        goto done;
    }
    lower = 1;
    if (!((center - (*((f32 *) (((char *) range) + 0xFC)))) <= 1.5f)) {
        lower = 0;
    }
    use(lower);
done:
    finish();
}
"""


def assembly(*rows):
    return '\n'.join(f'/* {i*4:X} {0x80000000+i*4:08X} 00000000 */ {row}' for i, row in enumerate(rows))


TARGET = assembly(
    'lwc1 $f0, 0x28($s2)',
    'lwc1 $f2, 0xfc($s1)',
    'c.lt.s $f12, $f24',
    'sub.s $f4, $f0, $f2',
    'lwc1 $f2, 0xf0($s1)',
    'bc1t .L2',
    'sub.s $f2, $f2, $f0',
    'c.le.s $f2, $f0',
    'c.le.s $f4, $f0',
)


def test_captures_both_distances_in_target_order():
    [(family, candidate)] = repair.variants(SOURCE, 'f', TARGET)
    assert family == repair.FAMILY
    assert 'center = *((f32 *)(actor + 0x28));\n    repair_lower_delta =' in candidate
    assert candidate.index('repair_lower_delta =') < candidate.index('repair_upper_delta =')
    assert candidate.index('repair_upper_delta =') < candidate.index('positive = 1;')
    assert 'if (!(repair_lower_delta <= 1.5f))' in candidate
    assert 'if (!(repair_upper_delta <= 1.5f))' in candidate


def test_requires_matching_center_register_and_both_target_comparisons():
    assert not repair.variants(SOURCE, 'f', TARGET.replace('sub.s $f2, $f2, $f0', 'sub.s $f2, $f2, $f1'))
    assert not repair.variants(SOURCE, 'f', TARGET.replace('c.le.s $f4, $f0', 'c.le.s $f6, $f0'))
    assert not repair.variants(SOURCE, 'f', TARGET.replace('0xfc($s1)', '0xfc($s2)'))


def test_skips_intervening_observable_changes():
    for line in ('    center = 0.0f;', '    *range = 0;', '    work();', '    external = 0;'):
        source = SOURCE.replace('    lower = 1;', line + '\n    lower = 1;')
        assert not repair.variants(source, 'f', TARGET)
