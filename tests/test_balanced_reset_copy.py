from decomprepair import balanced_reset_copy as repair

SOURCE = '''
typedef signed char s8;
typedef unsigned char u8;
typedef short s16;

inline static s8 byte_at(char *data, int offset) {
    return *((s8 *) (data + offset));
}

void apply(void *state) {
    struct {
        float vector[3];
        volatile float reserved_word;
    } frame;
    s8 sample;
    s16 saved;
    measure(&frame.vector[0]);
    if (((s8) (*((u8 *) (((char *) state) + 0x19)))) < 0) {
        sample = byte_at((char *) state, 0x36);
        *((u8 *) (((char *) state) + 0x19)) = 0xFU;
        saved = sample;
        sample = (sample < 0x64);
        if (sample) {
            *((s8 *) (((char *) state) + 0x36)) = (s8) (saved + 1);
        }
    }
}
'''
ROWS = [
    (' ', 'lb $v0, 0x19($s1)', 'lb $v0, 0x19($s1)'),
    (' ', 'bgez $v0, 0xc0', 'bgez $v0, 0xc0'),
    ('r', 'addiu $v0, $zero, 0xf', 'addiu $v1, $zero, 0xf'),
    ('r', 'lb $v1, 0x36($s1)', 'lb $v0, 0x36($s1)'),
    ('r', 'sb $v0, 0x19($s1)', 'sb $v1, 0x19($s1)'),
    ('r', 'move $v0, $v1', 'move $v1, $v0'),
    ('r', 'slti $v1, $v1, 0x64', 'slti $v0, $v0, 0x64'),
    ('r', 'beqz $v1, 0xb4', 'beqz $v0, 0xb4'),
    ('r', 'addiu $v0, $v0, 1', 'addiu $v0, $v1, 1'),
    (' ', 'sb $v0, 0x36($s1)', 'sb $v0, 0x36($s1)'),
]


def test_uses_the_widened_signed_copy_and_reclaims_the_trailing_word():
    [(tag, transformed)] = repair.variants(SOURCE, 'apply', ROWS)
    assert tag == repair.FAMILY
    assert 'reserved_word' not in transformed
    assert 'float vector[3];' in transformed
    assert 'saved = sample;\n        sample = (saved < 0x64);' in transformed
    assert transformed.index('sample = (saved') < transformed.index('= 0xFU;')
    assert '(s8) (saved + 1)' in transformed


def test_requires_linked_register_flow_and_shared_field_offsets():
    for rows in (
        ROWS[1:],
        ROWS[:3] + ROWS[4:],
        ROWS[:-1],
        [*ROWS[:7], ('i', ROWS[7][1], 'beqz $v0, 0xb8'), *ROWS[8:]],
    ):
        assert repair.variants(SOURCE, 'apply', rows) == []
    assert repair.variants(SOURCE.replace('0x36)) =', '0x45)) ='), 'apply', ROWS) == []


def test_preserves_observed_storage_and_signed_widths():
    for source in (
        SOURCE.replace('measure(&frame.vector[0]);', 'measure(&frame);'),
        SOURCE.replace('measure(&frame.vector[0]);', 'measure(&frame.reserved_word);'),
        SOURCE.replace('volatile float reserved_word;', 'volatile float reserved_word;\n        float next;'),
        SOURCE.replace('s16 saved;', 'u8 saved;'),
        SOURCE.replace('s8 sample;', 'volatile s8 sample;'),
        SOURCE.replace('s16 saved;', 'volatile s16 saved;'),
        SOURCE.replace('measure(&frame.vector[0]);', 'measure(&saved);'),
    ):
        assert repair.variants(source, 'apply', ROWS) == []


def test_honors_the_compiler_context_and_source_limit():
    assert not repair.variants(SOURCE, 'apply', ROWS, header='#define saved replacement')
    assert not repair.variants(SOURCE, 'apply', ROWS, max_bytes=64)
