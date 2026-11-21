from decomprepair.measured_cursor_publish import variants


def test_publish_the_cursor_after_the_measured_increment():
    source = """extern void *volatile stream;
void f(void) {
    void *cursor;
    s32 flag;
    cursor = stream;
    stream = cursor;
    flag = mode;
    cursor += 8;
    consume(flag);
}
"""
    rows = [
        ('<', 'addiu $a2, $a2, 8', ''),
        (' ', 'lui $at, %hi(stream)', 'lui $at, %hi(stream)'),
        (' ', 'sw $a2, %lo(stream)($at)', 'sw $a2, %lo(stream)($at)'),
    ]
    assert variants(source, 'f', rows) == [
        ('measured_cursor_publish', source.replace('stream = cursor;', 'stream = cursor + 8;')),
    ]
    assert not variants(source.replace('cursor += 8;', 'cursor += 4;'), 'f', rows)
    assert not variants(source, 'f', rows[1:])


def test_swap_measured_zero_initializers_before_a_shared_tail():
    source = """void f(s32 flags) {
    s32 a;
    register s32 b;
    a = 0;
    if (flags & 2) {
        b = 0;
        c = 255;
        goto shared;
    }
    if (flags & 4) {
        return;
    }
    {
        a = 255;
        b = 255;
shared:
        consume(a, b);
    }
}
"""
    rows = [
        ('r', 'move $a3, $zero', 'move $a1, $zero'),
        ('r', 'move $a1, $zero', 'move $a3, $zero'),
    ]
    [(family, fixed)] = variants(source, 'f', rows)
    assert family == 'measured_equal_zero_initializers'
    assert 'b = 0;\n    if (flags & 2) {\n        a = 0;' in fixed
    assert not variants(source.replace('a = 255;', 'consume(a); a = 255;'), 'f', rows)
    assert not variants(source, 'f', rows[:1])
