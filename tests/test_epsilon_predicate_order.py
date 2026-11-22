from decomprepair import epsilon_predicate_order as repair

SOURCE = '''
void f(f32 magnitude) {
    int var_v1_3;
    int var_v0_4;
    var_v1_3 = 1;
    if (!(magnitude <= 0.0002f)) {
        var_v1_3 = 0;
    }
    var_v0_4 = 1;
    if (!(magnitude >= (-0.0002f))) {
        var_v0_4 = 0;
    }
    if (((var_v1_3 ^ 1) | (var_v0_4 ^ 1)) == 0) {
        ready();
    }
}
'''

ROWS = [
    'c.le.s $f26, $f22',
    'bc1f .L1',
    'nop',
    'c.le.s $f20, $f26',
    'bc1t .L2',
    'xori $v1, $v1, 1',
    'move $v0, $zero',
    'xori $v0, $v0, 1',
    'or $v0, $v1, $v0',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def test_reorders_only_the_final_inverted_predicate_operands():
    [(family, candidate)] = repair.variants(SOURCE, 'f', asm(ROWS))
    assert family == repair.FAMILY
    assert candidate == SOURCE.replace('(var_v1_3 ^ 1) | (var_v0_4 ^ 1)', '(var_v0_4 ^ 1) | (var_v1_3 ^ 1)')


def test_preserves_already_ordered_or_nonmatching_predicates():
    for source in (SOURCE.replace('(-0.0002f)', '(-0.0003f)'),
                   SOURCE.replace('var_v1_3 = 0;', 'var_v1_3 = 2;'),
                   SOURCE.replace('int var_v1_3;', 'volatile int var_v1_3;'),
                   SOURCE.replace('(var_v1_3 ^ 1) | (var_v0_4 ^ 1)', '(var_v0_4 ^ 1) | (var_v1_3 ^ 1)')):
        assert not repair.variants(source, 'f', asm(ROWS))


def test_requires_target_predicate_pair_and_two_float_comparisons():
    assert not repair.variants(SOURCE, 'f', asm(ROWS[1:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:-1] + ['or $v0, $v0, $v1']))
