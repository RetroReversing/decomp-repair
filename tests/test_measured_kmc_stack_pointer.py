from decomprepair.measured_kmc_stack_pointer import FAMILY, variants

SOURCE = """void example(void)
{
    struct {
        f32 x;
        f32 y;
        f32 z;
        void *volatile record;
    } frame;
    f32 *vector;
    if (ready()) {
        void *state = frame.record;
        f32 a;
        a = first(state);
        a = second(a);
        frame.x = a;
        frame.y = -a;
        rotate(&frame.x);
        other(a);
        vector = &frame.x;
        consume(vector);
        copy(a, vector, vector);
        state = frame.record;
        consume(state);
    }
}
"""

ROWS = [
    ('r', 'addiu $a3, $sp, 0x10', 'addiu $t0, $sp, 0x10'),
    ('r', 'sw $a3, 0x24($sp)', 'sw $t0, 0x24($sp)'),
    (' ', 'lw $a0, 0x24($sp)', 'lw $a0, 0x24($sp)'),
    (' ', 'lw $a1, 0x24($sp)', 'lw $a1, 0x24($sp)'),
]


def test_pairs_stack_slot_with_preceding_call_scope():
    choices = variants(SOURCE, 'example', ROWS)
    expected = """        do {
            a = first(state);
            a = second(a);
            frame.x = a;
            frame.y = -a;
            rotate(&frame.x);
        } while (0);
"""
    candidate = next(source for family, source in choices if family == FAMILY and expected in source)
    assert 'unsigned int spillPadding[1];' in candidate
    assert 'f32 * volatile spillPointer;' in candidate
    assert 'state = &frame.x; frame.spillPointer = state;' in candidate
    assert 'copy(a, spillArgument, spillArgument);' in candidate
    assert 'state = frame.record;\n        consume(state);' in candidate


def test_requires_adjacent_register_only_differences_and_reloads():
    assert not variants(SOURCE, 'example', ROWS + [('r', 'move $v0, $a0', 'move $v0, $a1')])
    assert not variants(SOURCE, 'example', ROWS[:-1])
    assert not variants(SOURCE, 'example', [*ROWS[:3], (' ', 'sw $a1, 0x24($sp)', 'sw $a1, 0x24($sp)')])


def test_does_not_overwrite_a_live_carrier_or_rewrite_an_escaping_pointer():
    assert not variants(SOURCE.replace('consume(vector);', 'consume(vector, state);'), 'example', ROWS)
    assert not variants(SOURCE.replace('consume(vector);', 'consume(&vector);'), 'example', ROWS)
