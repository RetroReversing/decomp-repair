from decomprepair import float_forwarded_argument as repair

SOURCE = '''
f32 compute(void);
void f(void *object, int condition) {
    f32 amount;
    f32 result;
    amount = read_amount();
    if (condition) {
        result = 0.0f;
        adjust(object);
    } else {
        prepare(object);
        result = compute();
    }
    apply(object, amount, result);
}
'''

ROWS = [
    'jal compute',
    'mov.s $f12, $f24',
    'mfc1 $a1, $f24',
    'mfc1 $a2, $f0',
    'move $a0, $s2',
    'jal apply',
    'nop',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def test_restores_float_to_the_producer_and_splits_the_joined_call():
    [(family, candidate)] = repair.variants(SOURCE, 'f', asm(ROWS))
    assert family == repair.FAMILY
    assert 'f32 compute(f32);' in candidate
    assert 'result = compute(amount);' in candidate
    assert 'adjust(object);\n        apply(object, amount, 0.0f);' in candidate
    assert candidate.count('apply(object, amount, result);') == 1


def test_requires_matching_producer_and_consumer_registers():
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:2] + ['mfc1 $a1, $f22'] + ROWS[3:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:3] + ['mfc1 $a2, $f2'] + ROWS[4:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:4] + ['jal notify'] + ROWS[5:]))


def test_preserves_escaped_value_and_control_flow():
    for statement in ('record(&amount);', 'record(result);', 'if (retry()) goto elsewhere;'):
        source = SOURCE.replace('        adjust(object);', statement + '\n        adjust(object);')
        assert not repair.variants(source, 'f', asm(ROWS))
