from decomprepair.integer_lifetime_repairs import masked_phase_reuse

SOURCE = '''
unsigned f(unsigned input, unsigned color) {
    u32 earlier;
    s32 phase;
    earlier = input;
    sink(earlier);
    phase = color;
    sink((phase & 0xff) << 16);
    phase = input;
    if (phase < 0) sink(0);
    return 0;
}
'''


def test_reuses_disjoint_unsigned_local_for_only_the_masked_phase():
    [(family, candidate)] = masked_phase_reuse(SOURCE, 'f')
    assert family == 'merge_integer_lifetimes'
    assert 'earlier = color;' in candidate
    assert '((int)(earlier & 0xff)) << 16' in candidate
    assert 'phase = input;' in candidate
    assert 'if (phase < 0)' in candidate


def test_does_not_reuse_when_lifetimes_overlap():
    source = SOURCE.replace('phase = color;', 'phase = color;\n    sink(earlier);')
    assert not masked_phase_reuse(source, 'f')


def test_does_not_reuse_for_unmasked_read():
    assert not masked_phase_reuse(SOURCE.replace('(phase & 0xff)', 'phase'), 'f')


def test_does_not_reuse_when_a_branch_can_reach_the_read_without_the_write():
    source = SOURCE.replace('phase = color;', 'if (input) { phase = color; }')
    assert not masked_phase_reuse(source, 'f')


def test_does_not_use_a_block_local_outside_its_scope():
    source = SOURCE.replace('u32 earlier;', '').replace('earlier = input;\n    sink(earlier);',
                                                        '{ u32 earlier; earlier = input; sink(earlier); }')
    assert not masked_phase_reuse(source, 'f')


def test_does_not_change_the_precedence_of_an_unparenthesized_operand():
    source = SOURCE.replace('(phase & 0xff)', '(input + phase & 0xff)')
    assert not masked_phase_reuse(source, 'f')


def test_does_not_capture_arithmetic_after_the_mask():
    source = SOURCE.replace('(phase & 0xff)', '(phase & 0xff + 1)')
    assert not masked_phase_reuse(source, 'f')
