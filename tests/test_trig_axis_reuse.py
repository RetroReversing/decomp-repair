"""A completed float lifetime can carry the later shared projection axis."""

from decomprepair.trig_axis_reuse import FAMILY, variants

SOURCE = '''
extern f32 weight;
f32 sine(f32); f32 cosine(f32);
void adjust(char *record, f32 angle)
{
    f32 carry;
    f32 axis;
    f32 x;
    f32 z;
    carry = *((f32 *) (((char *) record) + 0x48));
    weight -= carry;
    x = 0.0f;
    z = 0.0f;
    axis = *((f32 *) (((char *) record) + 0x50));
    x += (axis * sine(angle));
    z += (axis * cosine(angle));
    report(x, z);
}
'''
ROWS = [
    (' ', 'lwc1 $f26, 0x48($s1)', 'lwc1 $f26, 0x48($s1)'),
    (' ', 'lui $at, %hi(weight)', 'lui $at, %hi(weight)'),
    (' ', 'lwc1 $f0, %lo(weight)($at)', 'lwc1 $f0, %lo(weight)($at)'),
    (' ', 'sub.s $f0, $f0, $f26', 'sub.s $f0, $f0, $f26'),
    ('r', 'lwc1 $f26, 0x50($s1)', 'lwc1 $f22, 0x50($s1)'),
    (' ', 'jal sine', 'jal sine'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f22, $f0'),
    (' ', 'jal cosine', 'jal cosine'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f22, $f0'),
]


def test_reuses_the_proven_saved_local_through_both_projections():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'carry = *((f32 *) (((char *) record) + 0x50));' in changed
    assert 'x += (carry * sine(angle));\n    z += (carry * cosine(angle));' in changed


def test_requires_matching_previous_field_and_both_calls():
    assert not variants(SOURCE, 'adjust', ROWS[4:])
    assert not variants(SOURCE, 'adjust', ROWS[:-1])
    assert not variants(SOURCE.replace('cosine(angle)', 'another(angle)'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('0x48', '0x54'), 'adjust', ROWS)


def test_refuses_escaped_or_live_carrier_and_remaining_axis_reads():
    assert not variants(SOURCE.replace('report(x, z);', 'report(x, z, carry);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report(x, z);', 'report(x, z, axis);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report(x, z);', 'report(x, z, &carry);'), 'adjust', ROWS)


def test_reuses_a_guarded_same_field_local_through_unwrapped_products():
    source = SOURCE.replace(
        '    carry = *((f32 *) (((char *) record) + 0x48));\n    weight -= carry;',
        '    carry = *((f32 *) (((char *) record) + 0x50));\n'
        '    ok = 1;\n'
        '    if (!(carry <= 0.025f)) {\n'
        '        *((f32 *) (((char *) record) + 0x38)) = carry;\n'
        '    }',
    ).replace('    f32 carry;', '    int ok;\n    f32 carry;')
    source = source.replace('(axis * sine(angle))', 'axis * sine(angle)')
    rows = [
        (' ', 'lwc1 $f26, 0x50($s1)', 'lwc1 $f26, 0x50($s1)'),
        (' ', 'c.le.s $f26, $f2', 'c.le.s $f26, $f2'),
        (' ', 'nop', 'nop'),
        (' ', 'bc1f .Lstore', 'bc1f .Lstore'),
        (' ', 'swc1 $f26, 0x38($s1)', 'swc1 $f26, 0x38($s1)'),
    ] + ROWS[4:]
    [(family, changed)] = variants(source, 'adjust', rows)
    assert family == FAMILY
    assert 'x += carry * sine(angle);' in changed
    assert 'z += (carry * cosine(angle));' in changed
    assert not variants(source, 'adjust', rows[5:])
    assert not variants(source.replace('0x38', '0x3c'), 'adjust', rows)
    assert not variants(source.replace('0x50', '0x54', 1), 'adjust', rows)
    assert not variants(source.replace('report(x, z);', 'report(x, z, carry);'), 'adjust', rows)
