from decomprepair import vector_output_capture as repair

SOURCE = '''
void f(void *context) {
    struct { f32 vector[3]; } frame;
    f32 x;
    f32 y;
    f32 z;
    load(frame.vector, 3);
    *((float *) context) = 0.0f;
    x = frame.vector[0];
    y = frame.vector[1];
    z = frame.vector[2];
    use(x, y, z);
}
'''
ROWS = [
    'jal load',
    'addiu $a0, $sp, 0x20',
    'lwc1 $f0, 0x20($sp)',
    'lwc1 $f2, 0x24($sp)',
    'lwc1 $f4, 0x28($sp)',
    'lw $v1, 0x68($s2)',
    'sw $zero, 0x34($v1)',
    'add.s $f0, $f0, $f2',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def test_captures_three_vector_outputs_before_the_following_store():
    [(family, text)] = repair.variants(SOURCE, 'f', asm(ROWS))
    assert family == repair.FAMILY
    assert 'load(frame.vector, 3);\n    repair_vector_0 = frame.vector[0];' in text
    assert text.index('repair_vector_2 =') < text.index('*((float *) context) =')
    assert 'y = repair_vector_1;' in text


def test_requires_all_three_consecutive_output_loads_before_target_store():
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:3] + ROWS[4:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:3] + [ROWS[6]] + ROWS[3:6]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:6] + [ROWS[7]]))


def test_skips_a_pointer_escape_or_buffer_write():
    for statement in ('saved = frame.vector;', 'saved = &frame;',
                      'saved = &frame.vector[1];', 'frame.vector[1] = 2.0f;'):
        source = SOURCE.replace('load(frame.vector, 3);', statement + '\n    load(frame.vector, 3);')
        assert not repair.variants(source, 'f', asm(ROWS))


def test_accepts_a_plain_stack_array():
    source = SOURCE.replace('struct { f32 vector[3]; } frame;', 'f32 vector[3];').replace('frame.vector', 'vector')
    [(_, text)] = repair.variants(source, 'f', asm(ROWS))
    assert 'repair_vector_0 = vector[0];' in text
