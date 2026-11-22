"""Reuse the guarded field local for a sampled phase with a witnessed scale."""

from decomprepair.sampled_phase_axis_stage import FAMILY, staged_variants, variants

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


STAGED_SOURCE = '''\
void update(void *record, int port)
{
    f32 first;
    f32 holder;
    f32 axis;
    f32 previous;
    f32 next;
    int guard;
    first = *((f32 *) (((char *) record) + 0x14));
    guard = 1;
    if (!(first <= 0.25f)) guard = 0;
    observe(first, guard);
    holder = *((f32 *) (((char *) record) + 0x14));
    guard = 1;
    if (!(holder <= 0.25f)) guard = 0;
    observe(holder, guard);
    axis = -sample(port, 4, 5);
    if (axis == 0.0f) {
        axis = sample(port, 2, 3);
    }
    previous = *((f32 *) (((char *) record) + 0x18));
    axis *= 4.0f;
    next = ((axis - previous) * 0.5f) + previous;
    observe(next, guard);
}
'''
GUARD = [
    'lwc1 $f26, 0x14($s0)', 'lui $at, 0x3e80', 'ori $at, $at, 0', 'mtc1 $at, $f2',
    'nop', 'c.le.s $f26, $f2',
]
GUARDS = [('r' if '$f26' in op else ' ', op, op.replace('$f26', '$f20')) for op in GUARD]
GUARDS += [(' ', op, op) for op in GUARD]
STAGED = [(' ', op, op) for op in [
    'addiu $a1, $zero, 4', 'jal sample', 'addiu $a2, $zero, 5',
    'lui $at, 0x3e80', 'ori $at, $at, 0',
]] + [
    ('r', 'mtc1 $at, $f22', 'mtc1 $at, $f26'),
    ('r', 'neg.s $f26, $f0', 'neg.s $f22, $f0'),
    ('r', 'c.le.s $f26, $f22', 'c.le.s $f22, $f26'),
] + [(' ', op, op) for op in ['lui $at, 0x4080', 'mtc1 $at, $f6', 'nop']] + [
    ('r', 'mul.s $f26, $f26, $f6', 'mul.s $f22, $f22, $f6'),
    (' ', 'lwc1 $f0, 0x18($s0)', 'lwc1 $f0, 0x18($s0)'),
    ('r', 'sub.s $f2, $f26, $f0', 'sub.s $f2, $f22, $f0'),
]


def test_reuses_the_ordered_guarded_holder_for_an_already_staged_scale():
    [(_, text)] = staged_variants(STAGED_SOURCE, 'update', GUARDS + STAGED)
    assert 'holder = -sample(port, 4, 5);' in text
    assert 'holder = sample(port, 2, 3);' in text
    assert 'holder *= 4.0f;' in text
    assert 'next = ((holder - previous) * 0.5f) + previous;' in text
    assert 'first = -sample' not in text


def test_the_staged_phase_requires_linked_witnesses_and_a_dead_holder():
    assert not staged_variants(STAGED_SOURCE, 'update', GUARDS[:6] + STAGED)
    assert not staged_variants(STAGED_SOURCE, 'update', GUARDS + STAGED[:-2])
    assert not staged_variants(STAGED_SOURCE.replace('axis *= 4.0f;', 'axis *= 8.0f;'), 'update', GUARDS + STAGED)
    assert not staged_variants(STAGED_SOURCE.replace('observe(next, guard);', 'observe(next, holder);'),
                               'update', GUARDS + STAGED)
    assert not staged_variants(STAGED_SOURCE.replace('observe(next, guard);', 'observe(next, axis);'),
                               'update', GUARDS + STAGED)
