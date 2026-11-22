from decomprepair.native_setup_call_zeros import FAMILY, variants

SOURCE = """
void reset(void *, int);
void f(void *actor) {
    union { unsigned int bits; float number; } cleared;
    float y;
    if (!actor) return;
    cleared.bits = (unsigned int)actor & ~(unsigned int)actor;
    {
        prepare(actor);
        cleared.bits = (cleared.bits >> 16) << 16;
        y = cleared.number;
        if (first) reset(actor, 1);
        if (second) {
            reset(actor, (int) cleared.bits);
        }
        cleared.bits = 0;
        if (third) {
            reset(actor, (int) cleared.bits);
        }
        draw(y);
    }
}
"""
ROWS = [
    (' ', 'move $s7, $zero', 'move $s7, $zero'),
    (' ', 'jal reset', 'jal reset'),
    ('r', 'move $a1, $zero', 'move $a1, $s7'),
    (' ', 'jal reset', 'jal reset'),
    ('r', 'move $a1, $zero', 'move $a1, $s7'),
]


def test_zero_calls_drop_two_proven_zero_arguments():
    [(family, trial)] = variants(SOURCE, 'f', ROWS)
    assert family == FAMILY
    assert trial.count('reset(actor, 0);') == 2
    assert 'reset(actor, 1);' in trial
    assert 'y = cleared.number;' in trial
    assert not variants(trial, 'f', ROWS)


def test_zero_calls_need_the_saved_register_and_both_delay_slots():
    assert not variants(SOURCE, 'f', ROWS[1:])
    assert not variants(SOURCE, 'f', ROWS[:-1])
    assert not variants(SOURCE, 'f', ROWS, max_bytes=20)
    assert not variants(SOURCE, 'f', ROWS, header='#define reset(x,y) store(x,y)')


def test_zero_calls_require_a_dominating_unescaped_zero_word():
    for source in (
        SOURCE.replace('cleared.bits = 0;', 'cleared.bits = 1;'),
        SOURCE.replace('cleared.bits = 0;', '(cleared.number) = 0.5f;'),
        SOURCE.replace('draw(y);', 'draw(&cleared);'),
        SOURCE.replace('prepare(actor);', 'prepare(actor, mutate(cleared.number));'),
        SOURCE.replace('cleared.bits = (unsigned int)actor', 'if (first)\n    cleared.bits = (unsigned int)actor'),
        SOURCE.replace('if (!actor) return;', 'if (!actor) goto skip;').replace('draw(y);', 'skip: draw(y);'),
    ):
        assert not variants(source, 'f', ROWS, header='#define mutate(x) ((x) = 1)')
