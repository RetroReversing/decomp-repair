from decomprepair.measured_event_frame_capture import variants

SOURCE = '''void setup(void *object, void *config) {
    s16 event;
    M2C_FIELD(object, s32 *, 0x3C) = -1;
    M2C_FIELD(object, u32 *, 0x44) = (u32) M2C_FIELD(config, u32 *, 0);
    M2C_FIELD(object, s32 *, 0x48) = 0x3E80;
    event = 5;
    post(&event);
}
'''
TARGET = ['addiu $sp, $sp, -0x40', 'lw $v1, ($s0)', 'move $s1, $a0', 'addiu $v0, $zero, -1',
          'sw $v0, 0x3c($s1)', 'addiu $v0, $zero, 0x3e80', 'sw $v0, 0x48($s1)',
          'sw $v1, 0x44($s1)', 'sh $v0, 0x18($sp)', 'addiu $a1, $sp, 0x18']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         'addiu $sp, $sp, -0x30' if i == 0 else 'nop') for i in range(75)]


def test_stages_count_and_reserves_event_space():
    result = variants(SOURCE, 'setup', '', ROWS)
    assert len(result) == 1
    code = result[0][1]
    assert 's16 event[9];' in code and 'post(&event[0]);' in code
    assert code.index('__repair_count = M2C_FIELD(config') < code.index('s32 *, 0x3C')
    assert code.index('s32 *, 0x48') < code.index('u32 *, 0x44')


def test_requires_frame_and_compatible_local_uses():
    assert not variants(SOURCE, 'setup', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('post(&event);', 'post(&event); use(event);'), 'setup', '', ROWS)
    assert not variants(SOURCE.replace('s16 event;', 'volatile s16 event;'), 'setup', '', ROWS)
    assert not variants(SOURCE.replace('event = 5;', '/* note */ event = 5;'), 'setup', '', ROWS)
