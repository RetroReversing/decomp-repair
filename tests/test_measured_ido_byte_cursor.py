from decomprepair.measured_ido_byte_cursor import variants

SOURCE = '''void send_header(Header *header, s32 size, s32 type) {
    u32 sent;
    Header *cursor;
    cursor = header;
    header->rev = 2;
    sent = 0;
    if (size != 0) {
        do {
            sent += send(cursor + sent, size - sent, 8);
        } while (sent < (u32) size);
    }
}
'''
TARGET = ['lw $t2, 0x2c($sp)', 'lw $t1, 0x28($sp)', 'lw $t3, 0x34($sp)',
          'addiu $a2, $zero, 8', 'addu $a0, $t1, $t2', 'jal send', 'subu $a1, $t3, $t2']
CANDIDATE = ['sll $t2, $t1, 2', 'subu $t2, $t2, $t1', 'sll $t2, $t2, 2',
             'addiu $a2, $zero, 8', 'addu $a0, $t2, $t3']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(40)]


def test_cursor_uses_byte_offsets():
    result = variants(SOURCE, 'send_header', '', ROWS)
    assert len(result) == 1
    assert 'char *cursor;' in result[0][1]
    assert 'cursor = (char *) header;' in result[0][1]


def test_requires_observed_scaling_and_exclusive_cursor_use():
    assert not variants(SOURCE, 'send_header', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('sent = 0;', 'use(cursor);\n    sent = 0;'), 'send_header', '', ROWS)
    assert not variants(SOURCE.replace('Header *cursor', 'volatile Header *cursor'), 'send_header', '', ROWS)
    assert not variants(SOURCE.replace('cursor = header;', '/* note */ cursor = header;'), 'send_header', '', ROWS)
