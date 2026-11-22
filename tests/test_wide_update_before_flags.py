"""A measured byte-store order can split a widened read from its narrow store."""

from decomprepair.wide_update_before_flags import FAMILY, variants

SOURCE = '''
extern double offset;
void adjust(char *state)
{
    *((unsigned char *) (((char *) state) + 12)) = 0U;
    *((signed char *) (((char *) state) + 8)) = 1;
    *((float *) (((char *) state) + 4)) = (float) ( ((double) (*((float *) (((char *) state) + 4)))) + offset );
}
'''
LOAD = 'lwc1 $f0, 4($s1)'
FIRST = 'sb $zero, 12($s1)'
SECOND = 'sb $v0, 8($s1)'
WIDE = ['lui $at, %hi(offset)', 'ldc1 $f2, %lo(offset)($at)', 'cvt.d.s $f0, $f0', 'add.d $f0, $f0, $f2']
WRITE = ['cvt.s.d $f0, $f0', 'swc1 $f0, 4($s1)']
SET = 'addiu $v0, $zero, 1'
ROWS = [
    (' ', SET, SET),
    (' ', LOAD, LOAD),
    ('o', '', FIRST),
    ('o', '', SECOND),
    *((' ', line, line) for line in WIDE),
    ('o', FIRST, ''),
    ('o', SECOND, ''),
    *((' ', line, line) for line in WRITE),
]


def test_stages_wide_expression_before_flags_and_keeps_narrow_store_after_them():
    [(label, candidate)] = variants(SOURCE, 'adjust', ROWS)
    assert label == FAMILY
    capture = candidate.index('double repair_wide_update =')
    first = candidate.index('state) + 12)) = 0U;')
    second = candidate.index('state) + 8)) = 1;')
    narrow = candidate.index('(float) repair_wide_update;')
    assert capture < first < second < narrow


def test_checks_base_offset_symbol_and_complete_target_sequence():
    assert not variants(SOURCE, 'adjust', ROWS[1:])
    assert not variants(SOURCE, 'adjust', ROWS[:-1])
    assert not variants(SOURCE.replace('state) + 8', 'other) + 8'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('state) + 8', 'state) + 6'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('extern double offset;', 'extern volatile double offset;'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('+ offset );', '+ different );'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('    *((unsigned char', '    if (enabled)\n    *((unsigned char'),
                        'adjust', ROWS)
