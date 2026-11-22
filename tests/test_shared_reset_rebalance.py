from decomprepair.shared_reset_rebalance import FAMILY, variants

SOURCE = """
extern float heading;
int prepare(void *);
int state(void *, int);

void f(void *p) {
    union { unsigned int bits; float number; } cleared;
    struct {
        volatile float speed;
    } frame;
    float y;
    float z;
    cleared.bits = (unsigned int)p & ~(unsigned int)p;
    frame.speed = cleared.number;
    heading = cleared.number;
    {
        float x = 0.0f;
        prepare(p);
        z = cleared.number;
        y = 0.0f;
        state(p, (int) cleared.bits);
        state(p, (int) cleared.bits);
        state(p, (int) cleared.bits);
        state(p, (int) cleared.bits);
        cleared.bits = 0;
        draw(p, cleared.number);
        heading = 0.0f;
        frame.speed = 0.0f;
        draw(p, x + y + z);
    }
}
"""
ROWS = [
    (' ', 'jal prepare', 'jal prepare'),
    ('r', 'move $s6, $s7', 'move $s5, $zero'),
    *[(' ', 'jal state', 'jal state'), ('r', 'move $a1, $zero', 'move $a1, $s7')] * 4,
    ('r', 'sw $s7, %lo(heading)($at)', 'sw $zero, %lo(heading)($at)'),
    ('r', 'sw $s7, 0x5c($sp)', 'sw $zero, 0x5c($sp)'),
]


def test_rebalance_reuses_zero_for_the_copy_and_both_stores():
    choices = variants(SOURCE, 'f', ROWS)
    assert len(choices) == 3
    assert all(family == FAMILY for family, _ in choices)
    assert [text.count('state(p, 0);') for _, text in choices] == [4, 2, 2]
    assert all(text.count('heading = cleared.number;') == 1
               and 'prepare((frame.speed = cleared.number, heading = cleared.number, p));' in text
               and 'y = cleared.number;' in text
               for _, text in choices)


def test_rebalance_requires_the_pair_and_unescaped_dominated_zero():
    assert not variants(SOURCE, 'f', ROWS[:-1])
    assert not variants(SOURCE, 'f', ROWS[2:])
    for changed in (
        SOURCE.replace('cleared.bits = 0;', 'cleared.bits = 7;'),
        SOURCE.replace('float z;', 'volatile float z;'),
        SOURCE.replace('int state(void *, int);', 'int state(void *, ...);'),
        SOURCE.replace('    cleared.bits', '    use(&cleared);\n    cleared.bits', 1),
        SOURCE.replace('    cleared.bits', '    use(&y);\n    cleared.bits', 1),
        SOURCE.replace('    cleared.bits', '    if (guard) goto inner;\n    cleared.bits', 1)
              .replace('        cleared.bits = 0;', '        inner: cleared.bits = 0;'),
        SOURCE.replace('        draw(p, cleared.number);', '        ((int) cleared.bits) = 3;'),
    ):
        assert not variants(changed, 'f', ROWS)
