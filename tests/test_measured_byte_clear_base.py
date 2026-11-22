from decomprepair.measured_byte_clear_base import variants

SOURCE = '''extern char table[];
void clear(s32 row) {
    s32 i;
    i = 0;
    do {
        *(((row & 0xFF) * 0xE) + table + (i & 0xFF)) = 0;
        i += 1;
    } while ((u32) (i & 0xFF) < 0xEU);
}
'''
TARGET = ['move $a1, $zero', 'andi $a0, $a0, 0xff', 'lui $v1, %hi(table)',
          'addiu $v1, $v1, %lo(table)', 'sll $v0, $a0, 3', 'subu $v0, $v0, $a0',
          'sll $v0, $v0, 1', 'addu $v1, $v0, $v1', 'andi $v0, $a1, 0xff',
          'addu $v0, $v1, $v0', 'sb $zero, ($v0)']
CANDIDATE = ['andi $v0, $v1, 0xff', 'addu $v0, $a0, $v0']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(20)]


def test_stages_base_before_clear_loop():
    result = variants(SOURCE, 'clear', '', ROWS)
    assert len(result) == 1
    assert 'do { __repair_base = table; __repair_base += row * 14; } while (0);' in result[0][1]
    assert '*(__repair_base + (i & 0xFF)) = 0;' in result[0][1]


def test_requires_target_and_unchanged_uses():
    assert not variants(SOURCE, 'clear', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('0xE)', '0xF)'), 'clear', '', ROWS)
    assert not variants(SOURCE.replace('i = 0;', 'i = row;'), 'clear', '', ROWS)
    assert not variants(SOURCE.replace('extern char', 'extern volatile char'), 'clear', '', ROWS)
