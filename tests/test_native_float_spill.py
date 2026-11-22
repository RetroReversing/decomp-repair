from decomprepair.native_float_spill import FAMILY, SETUP_COPY, setup_copy_variants, variants

FIELDS = (
    ('x', 'x_value', 0x4), ('y', 'y_value', 0x8), ('heading', 'heading_value', 0x10),
    ('frame.speed', 'speed_value', 0x14), ('z', 'z_value', 0xC), ('cleared.number', 'roll_value', 0x18),
)
SOURCE = """
extern float heading;
void f(void *p) {
    void *path;
    union { unsigned int bits; float number; } cleared;
    struct {
        int vector[3];
        unsigned int unused[2];
        volatile float speed;
    } frame;
    float y;
    float z;
    float x_value;
    float y_value;
    float z_value;
    float heading_value;
    float speed_value;
    float roll_value;
    path = *((void **) (((char *) p) + 0x2c));
    if (path) enter(path);
    {
        float x;
        cleared.bits = (unsigned int)p & ~(unsigned int)p;
        prepare((frame.speed = cleared.number, heading = cleared.number, p));
        x = 0.0f;
        y = cleared.number;
        z = 0.0f;
        if (first) {
            frame.speed = 0.0f;
            reset(p);
            *((float *) (((char *) p) + 0x14)) = frame.speed;
        }
        if (second) {
            cleared.bits = (unsigned int)p & ~(unsigned int)p;
            heading = cleared.number;
            frame.speed = cleared.number;
        }
        if (third) {
            frame.speed = 0.0f;
            reset(p);
            *((float *) (((char *) p) + 0x14)) = frame.speed;
        }
        refresh(p);
"""+''.join(
    f'        {local} = *(float *) (((char *) p) + 0x{offset:x});\n'
    f'        {local} = (float) ({local} + {delta});\n'
    for delta, local, offset in FIELDS
)+''.join(
    f'        *((float *) (((char *) p) + 0x{offset:x})) = {local};\n' for _, local, offset in FIELDS
)+"""
    }
}
"""
ROWS = [
    (' ', 'lw $t0, 0x2c($s2)', 'lw $t0, 0x2c($s2)'),
    (' ', 'sw $t0, 0x58($sp)', 'sw $t0, 0x58($sp)'),
    *[('r', 'lwc1 $f16, 0x50($sp)', 'lwc1 $f0, 0x50($sp)'),
      ('r', 'swc1 $f16, 0x14($s2)', 'swc1 $f0, 0x14($s2)')] * 2,
    (' ', 'sw $s7, %lo(heading)($at)', 'sw $s7, %lo(heading)($at)'),
    (' ', 'sw $s7, 0x50($sp)', 'sw $s7, 0x50($sp)'),
]


def test_native_slot_reopens_reload_and_separates_the_two_zero_definitions():
    [(family, candidate), (alternate_family, alternate)] = variants(SOURCE, 'f', ROWS)
    assert family == alternate_family == FAMILY
    assert candidate.index('float speed_delta;') < candidate.index('void *path;')
    assert 'unused[2]' not in candidate
    assert 'frame.speed' not in candidate
    assert 'heading = cleared.number;\n            cleared.bits = (cleared.bits >> 16) << 16;' in candidate
    assert candidate.index('z_value = *') < candidate.index('heading_value = *')
    first_order = ('roll', 'speed', 'y', 'x', 'z', 'heading')
    alternate_order = ('roll', 'speed', 'x', 'y', 'heading', 'z')
    for trial, order in ((candidate, first_order), (alternate, alternate_order)):
        indexes = [trial.index(f' = {name}_value;') for name in order]
        assert indexes == sorted(indexes)
        assert 'frame.speed' not in trial


def test_native_slot_requires_two_reloads_and_the_matching_paired_reset():
    assert not variants(SOURCE, 'f', ROWS[2:])
    assert not variants(SOURCE, 'f', ROWS[:4] + ROWS[6:])
    assert not variants(SOURCE, 'f', ROWS[:-1])
    assert not variants(SOURCE, 'f', ROWS, max_bytes=300)


def test_native_slot_rejects_observed_frame_and_mismatched_destinations():
    for candidate in (
        SOURCE.replace('refresh(p);', 'refresh(&frame);'),
        SOURCE.replace('refresh(p);', 'refresh(&frame.speed);'),
        SOURCE.replace('refresh(p);', 'refresh(&frame.unused[0]);'),
        SOURCE.replace('extern float heading;', 'extern volatile float heading;'),
        SOURCE.replace('refresh(p);', 'refresh(p, sizeof(frame));'),
        SOURCE.replace('0x14)) = frame.speed;', '0x1c)) = frame.speed;', 1),
        SOURCE.replace('float y;', 'volatile float y;'),
    ):
        assert not variants(candidate, 'f', ROWS)


SETUP_ROWS = [
    (' ', 'move $s7, $zero', 'move $s7, $zero'),
    ('r', 'move $a0, $s2', 'move $s5, $zero'),
    (' ', 'sw $s7, 0x50($sp)', 'sw $s7, 0x50($sp)'),
    (' ', 'lui $at, %hi(heading)', 'lui $at, %hi(heading)'),
    ('r', 'sw $s7, %lo(heading)($at)', 'sw $s5, %lo(heading)($at)'),
    (' ', 'jal prepare', 'jal prepare'),
    ('r', 'move $s6, $s7', 'move $a0, $s2'),
    (' ', 'lui $v0, %hi(first)', 'lui $v0, %hi(first)'),
    (' ', 'lbu $v0, %lo(first)($v0)', 'lbu $v0, %lo(first)($v0)'),
    ('r', 'move $fp, $s7', 'move $s6, $s5'),
    (' ', 'lwc1 $f16, 0x50($sp)', 'lwc1 $f16, 0x50($sp)'),
    (' ', 'lwc1 $f16, 0x50($sp)', 'lwc1 $f16, 0x50($sp)'),
]


def test_native_setup_copy_uses_the_cleared_word_after_the_call():
    candidate = variants(SOURCE, 'f', ROWS)[1][1]
    [(family, trial)] = setup_copy_variants(candidate, 'f', SETUP_ROWS)
    assert family == SETUP_COPY
    assert 'y = 0.0f;' not in trial
    lines = [line.strip() for line in trial.splitlines()]
    start = lines.index('prepare(p);')
    assert lines[start:start + 4] == [
        'prepare(p);', 'cleared.bits = (cleared.bits >> 16) << 16;', 'y = cleared.number;', 'if (first) {',
    ]
    assert not setup_copy_variants(trial, 'f', SETUP_ROWS)


def test_native_setup_copy_needs_both_reloads_and_a_private_zero_word():
    candidate = variants(SOURCE, 'f', ROWS)[1][1]
    assert not setup_copy_variants(candidate, 'f', SETUP_ROWS[:-1])
    assert not setup_copy_variants(candidate, 'f', SETUP_ROWS, max_bytes=20)
    for broken in (
        candidate.replace('prepare(p);', 'prepare(p, &cleared);'),
        candidate.replace('float y;', 'volatile float y;'),
        candidate.replace('if (first)', 'cleared.bits = 1;\n        if (first)', 1),
        candidate.replace('refresh(p);', 'refresh(p, &y);'),
    ):
        assert not setup_copy_variants(broken, 'f', SETUP_ROWS)
