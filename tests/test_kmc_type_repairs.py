from decomprepair.kmc_type_repairs import variants

COUNTER = [
    ('|', 'bnel $v0, $zero, loop', 'sltu $v0, $zero, $v0'),
    ('|', 'addiu $a1, $a1, 1', 'addu $a1, $a1, $v0'),
]
FLOAT_FORWARD = [
    (' ', 'jal step', 'jal step'),
    ('|', 'mov.s $f12, $f20', 'cvt.d.s $f12, $f20'),
]


def test_byte_counter_requires_a_matching_unit_increment_and_only_masked_reads():
    source = '''
s32 update(s32 enabled) {
    s32 count;
    count = 0;
    while (enabled-- > 0) {
        if (enabled & 1) count += 1;
        if ((count & 0xFF) == 2) break;
    }
    return (count & 255);
}
'''
    assert variants(source, 'update', '', COUNTER) == [
        ('kmc_byte_counter', source.replace('s32 count;', 'u8 count;')),
    ]
    assert not variants(source, 'update', '', [])
    assert not variants(source, 'update', '', COUNTER[:1])
    assert not variants(source.replace('(count & 255)', 'count'), 'update', '', COUNTER)
    assert not variants(source.replace('count += 1;', 'count += 1; count = count >> 1;'), 'update', '', COUNTER)


def test_float_forward_combines_the_entry_type_with_the_unprototyped_callee():
    source = '''
f32 step();
f32 update(s32 first, f32 second) {
    f32 value;
    value = step(first);
    return value + step(second);
}
'''
    assert variants(source, 'update', '', FLOAT_FORWARD) == [
        ('kmc_float_forward_prototype', source.replace('s32 first', 'f32 first').replace('step();', 'step(f32);')),
    ]
    assert not variants(source, 'update', 'f32 step(double);', FLOAT_FORWARD)
    assert not variants(source.replace('step(first)', 'step(first + 1)'), 'update', '', FLOAT_FORWARD)
    assert not variants(source, 'update', '', [(' ', 'jal other', 'jal other'), FLOAT_FORWARD[1]])
