from decomprepair.native_float_spill import FAMILY, variants

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
