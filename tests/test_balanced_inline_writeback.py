from decomprepair import balanced_inline_writeback as repair

SOURCE = '''
typedef signed char s8;
typedef float f32;
extern f32 heading_delta;

inline static s8 byte_at(char *data, int offset) {
    return *((s8 *) (data + offset));
}

void write_motion(void *actor, void *state) {
    struct { volatile float speed; } frame;
    union { unsigned int word; f32 number; } roll;
    unsigned char remaining;
    f32 x, y, z, heading, speed, pitch;
    f32 delta_x;
    f32 delta_y;
    f32 delta_z;
    delta_x = 0.5f;
    delta_y = 0.7f;
    delta_z = 0.9f;
    frame.speed = 0.0f;
    roll.word = 0;
    remaining = byte_at((char *) state, 0x15);
    if (remaining != 0) {
        *((s8 *) (((char *) state) + 0x15)) = (s8) (remaining - 1);
    } else {
        update(state);
    }
    x = (f32) ((*((f32 *) (((char *) actor) + 0x10))) + delta_x);
    heading = (f32) ((*((f32 *) (((char *) actor) + 0x20))) + heading_delta);
    y = (f32) ((*((f32 *) (((char *) actor) + 0x14))) + delta_y);
    z = (f32) ((*((f32 *) (((char *) actor) + 0x18))) + delta_z);
    speed = (f32) ((*((f32 *) (((char *) actor) + 0x1C))) + frame.speed);
    pitch = (f32) ((*((f32 *) (((char *) actor) + 0x24))) + roll.number);
    *((f32 *) (((char *) actor) + 0x10)) = x;
    *((f32 *) (((char *) actor) + 0x20)) = heading;
    *((f32 *) (((char *) actor) + 0x14)) = y;
    *((f32 *) (((char *) actor) + 0x18)) = z;
    *((f32 *) (((char *) actor) + 0x1C)) = speed;
    *((f32 *) (((char *) actor) + 0x24)) = pitch;
}
'''


def same(*ops):
    return [(' ', op, op) for op in ops]


COUNTDOWN = same('lb $v0, 0x15($s1)', 'beqz $v0, 0x74') + [
    ('<', 'move $v1, $v0', ''),
    ('r', 'addiu $v0, $v1, -1', 'addiu $v0, $v0, -1'),
] + same('j write_motion+0x88', 'sb $v0, 0x15($s1)')
ROWS = COUNTDOWN + same(*(['nop'] * 36), 'jal prepare_motion', 'nop',
                        'lwc1 $f12, 0x10($s2)', 'lwc1 $f6, 0x20($s2)', 'lwc1 $f8, 0x14($s2)',
                        'lwc1 $f10, 0x18($s2)', 'lwc1 $f4, 0x1c($s2)', 'lwc1 $f2, 0x24($s2)',
                        'mtc1 $s7, $f16') + [
    ('>', '', 'nop'),
    ('>', '', 'add.s $f2, $f2, $f16'),
] + same('swc1 $f12, 0x10($s2)', 'swc1 $f8, 0x14($s2)') + [
    ('<', 'add.s $f2, $f2, $f16', ''),
] + same('swc1 $f6, 0x20($s2)', 'swc1 $f10, 0x18($s2)', 'swc1 $f4, 0x1c($s2)',
         'j write_motion+0x184', 'swc1 $f2, 0x24($s2)', *(['nop'] * 9))


def test_balances_signed_byte_decrement_with_six_inlined_field_sums():
    [(tag, source)] = repair.variants(SOURCE, 'write_motion', ROWS)
    assert tag == repair.FAMILY
    assert 'if (*((s8 *) (((char *) state) + 0x15)) != 0)' in source
    assert '(*((s8 *) (((char *) state) + 0x15)))--;' in source
    assert source.count('repair_shifted_float(') == 7
    assert 'return *repair_field + repair_delta;' in source
    assert 'speed = repair_shifted_float((f32 *) (((char *) actor) + 0x1C), frame.speed);' in source
    assert '*((f32 *) (((char *) actor) + 0x24)) = pitch;' in source


def test_requires_the_countdown_shape_and_the_linked_load_store_group():
    for rows in (
        ROWS[len(COUNTDOWN):],
        [row for row in ROWS if row != ('>', '', 'nop')],
        [row for row in ROWS if row[1] != 'lwc1 $f2, 0x24($s2)'],
        [row for row in ROWS if row[1] != 'swc1 $f8, 0x14($s2)'],
    ):
        assert not repair.variants(SOURCE, 'write_motion', rows)


def test_rejects_incompatible_arithmetic_types_or_changed_fields():
    for source in (
        SOURCE.replace('f32 delta_x;', 'double delta_x;'),
        SOURCE.replace('extern f32 heading_delta;', 'extern double heading_delta;'),
        SOURCE.replace('volatile float speed;', 'volatile double speed;'),
        SOURCE.replace('f32 number;', 'double number;'),
        SOURCE.replace(')) = x;', ')) = heading;'),
        SOURCE.replace('remaining - 1', 'remaining - 2'),
        SOURCE.replace('signed char s8', 'unsigned char s8'),
        SOURCE.replace('f32 x,', 'volatile f32 x,'),
    ):
        assert not repair.variants(source, 'write_motion', ROWS)


def test_rejects_macros_and_excess_source_size():
    assert not repair.variants(SOURCE, 'write_motion', ROWS, header='#define delta_x 0.5f')
    assert not repair.variants(SOURCE, 'write_motion', ROWS, max_bytes=len(SOURCE) - 1)
