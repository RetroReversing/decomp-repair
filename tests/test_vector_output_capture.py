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


ORDER_SOURCE = SOURCE.replace(
    '    *((float *) context) = 0.0f;\n', '', 1,
).replace(
    '    f32 x;', '    void *record;\n    f32 x;',
).replace(
    '    use(x, y, z);',
    '    record = *((void **) (((char *) context) + 0x68));\n'
    '    *((float *) (((char *) record) + 0x34)) = 0.0f;\n'
    '    use(x, y, z);',
)
ORDER_ROWS = [
    (' ', ROWS[0], ROWS[0]),
    (' ', ROWS[1], ROWS[1]),
    ('o', '', ROWS[5]),
    *((' ', row, row) for row in ROWS[2:5]),
    ('o', ROWS[5], ''),
    *((' ', row, row) for row in ROWS[6:]),
]


def test_orders_three_existing_vector_loads_before_the_record_pointer():
    [(family, text)] = repair.ordered_snapshot_variants(ORDER_SOURCE, 'f', ORDER_ROWS)
    assert family == repair.ORDER_FAMILY
    assert 'x = ((volatile float *) frame.vector)[0];' in text
    assert 'y = ((volatile float *) frame.vector)[1];' in text
    assert 'z = ((volatile float *) frame.vector)[2];' in text
    assert 'record = *((void * volatile *)' in text
    assert text.count('load(frame.vector, 3);') == 1
    assert not repair.ordered_snapshot_variants(text, 'f', ORDER_ROWS)


def test_ordered_snapshot_requires_the_same_link_load_at_the_same_call():
    matched = [(' ', row, row) for row in ROWS]
    wrong_register = [
        (marker, target, candidate.replace('lw $v1,', 'lw $v0,'))
        for marker, target, candidate in ORDER_ROWS
    ]
    assert not repair.ordered_snapshot_variants(ORDER_SOURCE, 'f', matched)
    assert not repair.ordered_snapshot_variants(ORDER_SOURCE, 'f', wrong_register)
    assert not repair.ordered_snapshot_variants(ORDER_SOURCE, 'f', ORDER_ROWS[:4] + ORDER_ROWS[5:])
    assert not repair.ordered_snapshot_variants(ORDER_SOURCE, 'f', ORDER_ROWS + matched)


def test_ordered_snapshot_requires_source_triplet_followed_by_the_witnessed_read():
    for source in (
        ORDER_SOURCE.replace('context) + 0x68', 'context) + 0x64'),
        ORDER_SOURCE.replace('y = frame.vector[1];', 'x = frame.vector[1];'),
        ORDER_SOURCE.replace('y = frame.vector[1];', 'y = frame.vector[2];'),
        ORDER_SOURCE.replace('y = frame.vector[1];', 'other();\n    y = frame.vector[1];'),
        ORDER_SOURCE.replace('load(frame.vector, 3);', 'saved = frame.vector;\n    load(frame.vector, 3);'),
    ):
        assert not repair.ordered_snapshot_variants(source, 'f', ORDER_ROWS)
