from decomprepair import scoped_phase_initializer as repair

SOURCE = '''
typedef float f32;
typedef unsigned char u8;

void update(void *actor, int active) {
    f32 accumulated;
    f32 depth;
    f32 vertical;
    u8 count;
    struct { f32 speed; } frame;
    struct { f32 zero; } start;
    int state;
    if (active) goto moving;
    goto stationary;
moving:
    start.zero = 0.0f;
    frame.speed = 0.0f;
    heading = 0.0f;
    depth = start.zero;
    prepare(actor);
    vertical = 0.0f;
    if (airborne != 0) {
        adjust(actor);
    }
    accumulated = 0.0f;
    count = *((u8 *) (((char *) actor) + 0x18));
    if (count != 0) {
        *((u8 *) (((char *) actor) + 0x18)) = (u8) (count - 1);
    }
    state = read_state(actor);
    switch (state) {
    case 1:
        accumulated += 1.0f;
        break;
    default:
        break;
    }
    record(accumulated, depth, vertical);
    goto complete;
stationary:
    stop_motion(actor);
complete:
    done(actor);
}
'''


def same(*operations):
    return [(' ', op, op) for op in operations]


ROWS = same(*(['nop'] * 6), 'jal prepare', 'move $a0, $s2',
            'lui $v0, %hi(airborne)', 'lbu $v0, %lo(airborne)($v0)') + [
    ('<', 'move $fp, $s7', ''),
    ('i', 'beqz $v0, 0x64', 'beqz $v0, 0x60'),
] + same(*(['nop'] * 11), 'lbu $v0, 0x18($s1)') + [
    ('|', 'beqz $v0, 0x80 [bytes 10400002]', 'beqz $v0, 0x80 [bytes 10400003]'),
    ('>', '', 'move $s5, $zero'),
] + same('addiu $v0, $v0, -1', 'sb $v0, 0x18($s1)')


def test_scopes_the_initializer_between_the_reset_stores_and_setup():
    [(tag, generated)] = repair.variants(SOURCE, 'update', ROWS)
    assert tag == repair.FAMILY
    assert 'f32 accumulated;' not in generated
    assert generated.count('accumulated = 0.0f;') == 1
    assert 'heading = 0.0f;\n    {\n    f32 accumulated = 0.0f;\n    depth' in generated
    assert '\n    goto complete;\n}\nstationary:' in generated
    assert 'record(accumulated, depth, vertical);' in generated


def test_requires_the_delayed_move_and_matching_source_evidence():
    assert not repair.variants(SOURCE, 'update', [row for row in ROWS if row[2] != 'move $s5, $zero'])
    assert not repair.variants(SOURCE, 'update', [row for row in ROWS if row[1] != 'jal prepare'])
    assert not repair.variants(SOURCE.replace('if (airborne', 'if (grounded'), 'update', ROWS)
    assert not repair.variants(SOURCE.replace('0x18));', '0x19));', 1), 'update', ROWS)


def test_keeps_external_control_edges_and_escaped_locals_unchanged():
    for candidate in (
        SOURCE.replace('goto stationary;', 'goto bypass;').replace('    accumulated =', 'bypass:\n    accumulated ='),
        SOURCE.replace('    state = read_state(actor);', '    case 7: state = read_state(actor);'),
        SOURCE.replace('    prepare(actor);', '    prepare(&accumulated);'),
        SOURCE.replace('    stop_motion(actor);', '    stop_motion(accumulated);'),
        SOURCE.replace('    adjust(actor);', '    adjust(accumulated);'),
        SOURCE.replace('    f32 accumulated;', '    volatile f32 accumulated;'),
    ):
        assert not repair.variants(candidate, 'update', ROWS)


def test_honors_macro_names_and_the_source_limit():
    assert not repair.variants(SOURCE, 'update', ROWS, header='#define accumulated symbol')
    assert not repair.variants(SOURCE, 'update', ROWS, max_bytes=64)


SHARED_SOURCE = '''
extern float heading;
void update(void *p) {
    union { unsigned int bits; float number; } reset;
    struct { volatile float speed; } frame;
    float depth;
    float vertical;
    reset.bits = (unsigned int)p & ~(unsigned int)p;
    frame.speed = reset.number;
    heading = 0.0f;
    {
        float horizontal = 0.0f;
        depth = reset.number;
        prepare(p);
        vertical = 0.0f;
        if (active) {
            record(horizontal, depth, vertical);
        }
    }
}
'''
SHARED_ROWS = [
    *same('move $s7, $zero', 'sw $s7, 0x3c($sp)', 'lui $at, %hi(heading)'),
    ('r', 'sw $s7, %lo(heading)($at)', 'sw $zero, %lo(heading)($at)'),
    *same('jal prepare'),
    ('r', 'move $s6, $s7', 'move $s5, $zero'),
]


def test_shared_setup_zero_keeps_global_store_before_call_and_delays_local_copy():
    [(family, candidate)] = repair.shared_zero_variants(SHARED_SOURCE, 'update', SHARED_ROWS)
    assert family == repair.SHARED_ZERO
    assert candidate.index('heading = reset.number;') < candidate.index('prepare(p);')
    assert candidate.index('prepare(p);') < candidate.index('depth = reset.number;')


def test_shared_setup_zero_requires_known_float_view_and_unescaped_local_copy():
    for source in (
        SHARED_SOURCE.replace('reset.bits = (unsigned int)p & ~(unsigned int)p;', 'reset.bits = input;'),
        SHARED_SOURCE.replace('extern float heading;', 'extern volatile float heading;'),
        SHARED_SOURCE.replace('    float depth;', '    volatile float depth;'),
        SHARED_SOURCE.replace('    reset.bits', '    escape(&depth);\n    reset.bits'),
        SHARED_SOURCE.replace('    reset.bits', '    escape(&reset);\n    reset.bits'),
    ):
        assert not repair.shared_zero_variants(source, 'update', SHARED_ROWS)
    assert not repair.shared_zero_variants(SHARED_SOURCE, 'update', SHARED_ROWS[1:])
