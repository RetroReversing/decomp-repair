"""Coalesce one shared projection input into its final saved result."""

from decomprepair.shared_projection_lifetime import FAMILY, variants

SOURCE = '''
f32 adjust(char *record, f32 angle, int choose)
{
    f32 seed;
    f32 output;
    f32 horizontal;
    if (choose) goto zero_entry;
    seed = 0.2f;
    shared:
    *((f32 *) (((char *) record) + 0x4C)) = seed;
    horizontal = seed * sine(angle);
    output = seed * cosine(angle);
    emit(horizontal);
    return output;
    zero_entry:
    seed = 0.0f;
    goto shared;
}
'''
ROWS = [
    (' ', 'lui $at, 0x3e4c', 'lui $at, 0x3e4c'),
    (' ', 'ori $at, $at, 0xcccd', 'ori $at, $at, 0xcccd'),
    ('r', 'mtc1 $at, $f26', 'mtc1 $at, $f20'),
    (' ', 'nop', 'nop'),
    ('r', 'swc1 $f26, 0x4c($s1)', 'swc1 $f20, 0x4c($s1)'),
    (' ', 'jal sine', 'jal sine'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f20, $f0'),
    (' ', 'jal cosine', 'jal cosine'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f26, $f26, $f0', 'mul.s $f26, $f20, $f0'),
    ('r', 'mtc1 $zero, $f12', 'mtc1 $zero, $f4'),
    ('i', 'bnez $v0, 0x10', 'bnez $v0, 0x14'),
    ('r', 'mov.s $f26, $f12', 'mov.s $f20, $f4'),
]


def test_coalesces_both_seeds_and_projection_reads():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'output = 0.2f;' in changed and 'output = 0.0f;' in changed
    assert 'output = output * cosine(angle);' in changed
    assert 'horizontal = output * sine(angle);' in changed


def test_requires_the_alternate_branch_and_exact_field_and_literals():
    assert not variants(SOURCE, 'adjust', ROWS[:-1])
    assert not variants(SOURCE.replace('0x4C', '0x50'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('0.2f', '0.25f'), 'adjust', ROWS)
    wrong_branch = ROWS[:-2] + [('i', 'bnez $v0, 0x14', 'bnez $v0, 0x10'), ROWS[-1]]
    assert not variants(SOURCE, 'adjust', wrong_branch)


def test_keeps_distinct_lifetimes_when_the_output_must_stay_live():
    assert not variants(SOURCE.replace('sine(angle)', 'sine(output)'), 'adjust', ROWS)
    escaped = SOURCE.replace('emit(horizontal);', 'emit(horizontal, &output);')
    assert not variants(escaped, 'adjust', ROWS)
    read_seed = SOURCE.replace('return output;', 'return output + seed;')
    assert not variants(read_seed, 'adjust', ROWS)
