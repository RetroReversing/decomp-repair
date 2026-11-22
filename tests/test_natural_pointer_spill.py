from decomprepair.natural_pointer_spill import FAMILY, variants

SOURCE = """
int reset(void *, int);
void use(void *);
void f(void *p) {
    void *saved;
    union { unsigned int bits; float number; } cleared;
    struct {
        float local;
        unsigned int padding;
        void *room;
    } frame;
    saved = *((void **) (((char *) p) + 0x18));
    frame.room = saved;
    use(frame.room);
    use(frame.room);
    cleared.bits = (unsigned int)p & ~(unsigned int)p;
    frame.local = 0.0f;
    {
        reset(p, 0);
        use(frame.room);
        reset(p, 0);
        use(frame.room);
        reset(p, 0);
        cleared.bits = 0;
        reset(p, 0);
    }
}
"""
ROWS = [
    ('r', 'lw $t0, 0x18($s2)', 'lw $v0, 0x18($s2)'),
    (' ', 'move $s3, $s2', 'move $s3, $s2'),
    ('r', 'sw $t0, 0x50($sp)', 'sw $v0, 0x50($sp)'),
    *[(' ', 'jal reset', 'jal reset'), (' ', 'move $a1, $zero', 'move $a1, $zero')] * 4,
    *[('r', 'lw $t0, 0x50($sp)', 'lw $v0, 0x50($sp)'),
      ('r', 'lw $v0, 0x10($t0)', 'lw $v0, 0x10($v0)')] * 2,
]


def test_shared_reset_reopens_natural_pointer_spill_and_removes_unused_tail_words():
    family, candidate = variants(SOURCE, 'f', ROWS)[0]
    assert family == FAMILY
    assert candidate.count('use(saved);') == 4
    assert candidate.count('reset(p, (int) cleared.bits);') == 4
    assert 'padding' not in candidate
    assert 'room' not in candidate
    assert not variants(SOURCE, 'f', ROWS, max_bytes=30)


def test_pointer_spill_requires_matching_entry_and_two_nested_reloads():
    assert not variants(SOURCE, 'f', ROWS[:-2])
    assert not variants(SOURCE, 'f', ROWS[1:])
    assert not variants(SOURCE, 'f', ROWS[:9] + ROWS[11:])


def test_pointer_spill_requires_unaliased_pointer_and_initialized_zero_on_every_path():
    for before, after in (
        ('    cleared.bits = ', '    if (!p) goto entered;\n    cleared.bits = '),
        ('use(frame.room);', 'use(&frame.room);'),
        ('use(frame.room);', 'use(&frame);'),
        ('use(frame.room);', 'use(frame.room); (frame.room) = p;'),
        ('cleared.bits = 0;', 'cleared.bits = 1;'),
        ('cleared.bits = 0;', '(cleared.number) = 1.0f;'),
        ('cleared.bits = 0;', 'use(&cleared.bits);'),
        ('cleared.bits = 0;', 'use(&p);'),
    ):
        before_source = SOURCE
        if 'goto entered' in after:
            before_source = before_source.replace('        cleared.bits = 0;', '        entered: cleared.bits = 0;')
        assert not variants(before_source.replace(before, after, 1), 'f', ROWS), after


def test_target_saved_zero_store_can_reuse_the_same_reset():
    rows = ROWS + [
        (' ', 'move $s7, $zero', 'move $s7, $zero'),
        ('r', 'sw $s7, 0x20($sp)', 'sw $zero, 0x20($sp)'),
    ]
    choices = variants(SOURCE, 'f', rows)
    assert len(choices) == 2
    assert 'frame.local = cleared.number;' in choices[1][1]
