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


SAVED_FOR_ARGUMENT = [
    (' ', 'move $a0, $s0', 'move $a0, $s0'),
    ('r', 'subu $a1, $s0, $a1', 'subu $a1, $a0, $a1'),
]
SIGN_LOCAL = '''
void f(void *a) {
    s16 mode = 0;
    switch (kind) {
    case 1: mode = 4; break;
    case 2: mode = 0x16; break;
    }
    first = mode - first;
    use(mode, first);
}'''


def test_a_sign_extended_local_assigned_only_small_literals_is_widened_when_the_target_reads_its_own_register():
    [(family, result)] = variants(SIGN_LOCAL, 'f', '', SAVED_FOR_ARGUMENT)
    assert family == 'kmc_widen_sign_local'
    assert 's32 mode = 0;' in result and 's16' not in result
    # no saved-for-argument row, no proposal: the search does not spend compiles on it
    assert not variants(SIGN_LOCAL, 'f', '', [('r', 'addu $a1, $a1, $a2', 'addu $a1, $a1, $a3')])
    assert not variants(SIGN_LOCAL, 'f', '', [('r', 'subu $a1, $s0, $a1', 'subu $a1, $s1, $a1')])


def test_widening_refuses_what_could_change_the_program():
    for text in (SIGN_LOCAL.replace('mode = 4;', 'mode = read();'),        # not a literal
                 SIGN_LOCAL.replace('mode = 4;', 'mode += 4;'),            # compound
                 SIGN_LOCAL.replace('mode = 4;', 'mode = 40000;'),         # does not fit
                 SIGN_LOCAL.replace('use(mode', 'use(&mode'),              # address taken
                 SIGN_LOCAL.replace('mode = 4;', 'mode++;'),
                 SIGN_LOCAL.replace('void f', 'volatile int v; void f').replace('first =', 'asm("x"); first =')):
        assert not variants(text, 'f', '', SAVED_FOR_ARGUMENT), text
