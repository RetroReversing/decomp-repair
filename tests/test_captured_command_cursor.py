from decomprepair import measured_cursor_publish

SOURCE = """extern void *commands;
void f(void) {
    *((s32 *) (((char *) commands) + 0)) = 0xDB080000;
    scale = tint;
    *((s32 *) (((char *) commands) + 4)) = scale;
    red = r;
    commands = commands + 8;
    blue = b;
    green = g;
}"""
ROWS = [
    ('r', 'sw $v0, ($a2)', 'sw $v0, ($v1)'),
    ('>', '', 'lw $v0, %lo(commands)($v0)'),
    ('r', 'sw $a0, 4($a2)', 'sw $a0, 4($v0)'),
    ('r', 'lbu $v0, %lo(r)($v0)', 'lbu $v1, %lo(r)($v1)'),
    ('i', 'lbu $v1, %lo(g)($v1)', 'lbu $a0, %lo(b)($a0)'),
    ('i', 'lbu $a0, %lo(b)($a0)', 'lbu $a1, %lo(g)($a1)'),
    ('r', 'addiu $a2, $a2, 8', 'addiu $v0, $v0, 8'),
    ('r', 'sw $a2, %lo(commands)($at)', 'sw $v0, %lo(commands)($at)'),
    ('r', 'sb $v0, %lo(red)($at)', 'sb $v1, %lo(red)($at)'),
    ('i', 'sb $v1, %lo(green)($at)', 'sb $a0, %lo(blue)($at)'),
    ('i', 'sb $a0, %lo(blue)($at)', 'sb $a1, %lo(green)($at)'),
]


def test_captures_cursor_and_uses_target_byte_store_order():
    (family, candidate), = measured_cursor_publish.variants(SOURCE, 'f', ROWS)
    assert family == 'measured_captured_command_cursor'
    assert candidate.count('(char *) repair_command_cursor') == 2
    assert candidate.index('green = g;') < candidate.index('blue = b;')
    assert 'repair_command_cursor += 8;' in candidate
    assert 'commands = repair_command_cursor;' in candidate


def test_requires_reload_and_matching_byte_stores():
    assert measured_cursor_publish.variants(SOURCE, 'f', ROWS[2:]) == []
    assert measured_cursor_publish.variants(SOURCE.replace('green = g;', 'green = b;'), 'f', ROWS) == []
