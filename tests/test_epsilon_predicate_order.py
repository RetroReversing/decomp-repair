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


STAGED_SOURCE = SOURCE.replace(
    '    int var_v0_4;', '    int var_v0_4;\n    int held;',
).replace(
    '    var_v0_4 = 1;', '    held = var_v1_3 ^ 1;\n    var_v0_4 = 1;',
).replace(
    '(var_v1_3 ^ 1) | (var_v0_4 ^ 1)', '(var_v0_4 ^ 1) | held',
)
STAGED_ROWS = [
    'lui $at, 0x3951',
    'ori $at, $at, 0xb717',
    'mtc1 $at, $f0',
    'nop',
    'c.le.s $f26, $f0',
    'nop',
    'nop',
    'bc1t .Lfirst',
    'addiu $v1, $zero, 1',
    'move $v1, $zero',
    'lui $at, 0xb951',
    'ori $at, $at, 0xb717',
    'mtc1 $at, $f0',
    'nop',
    'c.le.s $f0, $f26',
    'addiu $v0, $zero, 1',
    'nop',
    'bc1t .Lsecond',
    'xori $v1, $v1, 1',
    'move $v0, $zero',
    'xori $v0, $v0, 1',
]
STAGED_DIFF = [(' ', op, op) for op in STAGED_ROWS] + [('r', 'or $v0, $v1, $v0', 'or $v0, $v0, $v1')]


def test_preserves_the_staged_inversion_and_orders_both_or_operands():
    [(family, changed)] = repair.staged_variants(STAGED_SOURCE, 'f', STAGED_DIFF)
    assert family == repair.STAGED
    assert changed == STAGED_SOURCE.replace('(var_v0_4 ^ 1) | held', 'held | (var_v0_4 ^ 1)')


def test_staged_ordering_stays_gated_on_measured_sites_and_exact_epsilon():
    assert not repair.staged_variants(STAGED_SOURCE, 'f', STAGED_DIFF[:-1])
    assert not repair.staged_variants(STAGED_SOURCE, 'f', STAGED_DIFF * 2)
    assert not repair.staged_variants(STAGED_SOURCE, 'f', STAGED_DIFF[:18] + STAGED_DIFF[19:])
    assert not repair.staged_variants(STAGED_SOURCE.replace('0.0002f', '0.0003f'), 'f', STAGED_DIFF)
    assert not repair.staged_variants(STAGED_SOURCE.replace('int held;', 'volatile int held;'), 'f', STAGED_DIFF)
    assert not repair.staged_variants(STAGED_SOURCE.replace('ready();', 'ready(&held);'), 'f', STAGED_DIFF)
