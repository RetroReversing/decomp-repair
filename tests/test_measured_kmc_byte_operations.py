from decomprepair.measured_kmc_byte_operations import variants

RESOLVE = {'table': 0x80001200, 'last': 0x80001203}.get


def measured(ops):
    return [(' ', op, op) for op in ops]


def change(rows, index, value):
    rows[index] = ('i', rows[index][1], value)


def word_table(rows, high):
    rows.insert(high, ('>', '', 'sll $v1, $v1, 2'))
    for i in range(high + 1, len(rows)):
        if '%hi(table)' in rows[i][1] or '%lo(table)' in rows[i][1]:
            change(rows, i, rows[i][1].replace('table', 'last'))


def test_linked_byte_table_removes_word_scale():
    source = '''
extern M2C_UNK table;
u8 f(int index) {
    return *(&table + (index & 7));
}
'''
    rows = measured((
        'andi $v1, $a0, 7', 'nop', 'nop', 'nop', 'nop', 'nop', 'nop',
        'lui $v0, %hi(table)', 'addu $v0, $v0, $v1', 'jr $ra', 'lbu $v0, %lo(table)($v0)',
    ))
    word_table(rows, 7)
    [(family, fixed)] = variants(source, 'f', '', rows, RESOLVE)
    assert family == 'measured_byte_table_index'
    assert '((u8 *)&table)[(index & 7)]' in fixed
    assert not variants(source, 'f', '', rows)
    assert not variants(source, 'f', '', rows, {'table': 0x80001200, 'last': 0x80001201}.get)


def test_linked_byte_index_and_buffer_share_element_width():
    source = '''
extern M2C_UNK table;
extern s32 bytes;
void f(int index) {
    copy(*(&table + index), (index * 24) + &bytes, 24);
}
'''
    rows = measured((
        'addiu $sp, $sp, -24', 'sw $ra, 16($sp)', 'move $v1, $a0',
        'sll $a1, $a1, 3', 'lui $v0, %hi(bytes)', 'addiu $v0, $v0, %lo(bytes)',
        'lui $a0, %hi(table)', 'addu $a0, $a0, $v1', 'lbu $a0, %lo(table)($a0)',
        'jal copy', 'addiu $a2, $zero, 24', 'lw $ra, 16($sp)', 'jr $ra', 'addiu $sp, $sp, 24',
    ))
    change(rows, 3, 'sll $a1, $a1, 5')
    word_table(rows, 6)
    [(_, fixed)] = variants(source, 'f', '', rows, RESOLVE)
    assert 'extern u8 bytes;' in fixed
    assert 'copy(((u8 *)&table)[index]' in fixed
    [(_, fixed)] = variants(source, 'f', 'extern s32 bytes;', rows, RESOLVE)
    assert 'extern s32 bytes;' in fixed


def test_word_flag_uses_the_call_register_without_changing_prototypes():
    source = '''
void deliver(s32, u8);
extern void *state;
void f(s32 dest) {
    u8 flags;
    flags = M2C_FIELD(state, u8 *, 32) | 4;
    M2C_FIELD(state, u8 *, 32) = flags;
    deliver(dest, flags);
}
'''
    target = ('lui $v1, %hi(state)', 'lw $v1, %lo(state)($v1)', 'lbu $a1, 32($v1)', 'move $s0, $v0',
              'move $a0, $s0', 'ori $a1, $a1, 4', 'jal deliver', 'sb $a1, 32($v1)')
    rows = measured(('addiu $sp, $sp, -24', 'nop', *target, 'jr $ra', 'addiu $sp, $sp, 24'))
    for i in (4, 7, 9):
        change(rows, i, rows[i][1].replace('$a1', '$a2'))
    rows.insert(8, ('>', '', 'move $a1, $a2'))
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_word_flag_argument'
    assert 's32 flags;' in fixed
    assert 'void deliver(s32, u8);' in fixed
    assert not variants(source.replace('deliver(dest, flags);', 'deliver(dest, flags); return flags;'), 'f', '', rows)


def test_signed_halfword_is_boolean_before_comparison():
    source = '''
extern u8 mode;
extern s16 status;
s32 f(s32 arg) {
    s32 result;
    result = 1;
    if (mode == 3) {
        result = (status) >= (arg & 0xFF);
    }
    return result & 0xFF;
}
'''
    rows = measured((
        'lui $v1, %hi(mode)', 'lbu $v1, %lo(mode)($v1)', 'addiu $v0, $zero, 3',
        'bne $v1, $v0, 44', 'addiu $a1, $zero, 1', 'lui $v0, %hi(status)', 'lh $v0, %lo(status)($v0)',
        'sltu $v0, $zero, $v0', 'andi $v1, $a0, 255', 'slt $v0, $v0, $v1',
        'xori $a1, $v0, 1', 'jr $ra', 'andi $v0, $a1, 255',
    ))
    rows[7] = ('<', rows[7][1], '')
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_halfword_status_test'
    assert 's16 value) { return value != 0;' in fixed
    assert '(__repair_halfword_nonzero(status)) >=' in fixed
    assert not variants(source.replace('extern s16 status;', 'extern u16 status;'), 'f', '', rows)


def test_clamped_byte_table_accumulates_in_halfword_local():
    source = '''
extern M2C_UNK table;
void f(s32 x, s32 y) {
    s32 col; s32 row;
    col = x;
    row = y;
    if ((u32) (col & 0xFFFF) >= 0xAU) { col = 9; }
    if ((u32) (row & 0xFFFF) >= 2U) { row = 1; }
    show(*(&table + ((col + ((row & 0xFFFF) * 10)) & 0xFFFF)), row);
}
'''
    rows = measured((
        'addiu $sp, $sp, -24', 'andi $v0, $a0, 65535', 'sltiu $v0, $v0, 10', 'bnez $v0, 24',
        'sw $ra, 16($sp)', 'addiu $a0, $zero, 9', 'andi $v0, $a1, 65535', 'sltiu $v0, $v0, 2',
        'beql $v0, $zero, 40', 'addiu $a1, $zero, 1', 'andi $v0, $a1, 65535', 'sll $v1, $v0, 2',
        'addu $v1, $v1, $v0', 'sll $v1, $v1, 1', 'addu $a0, $a0, $v1', 'andi $v0, $a0, 65535',
        'lui $a0, %hi(table)', 'addu $a0, $a0, $v0', 'jal show', 'lbu $a0, %lo(table)($a0)',
        'lw $ra, 16($sp)', 'jr $ra', 'addiu $sp, $sp, 24',
    ))
    word_table(rows, 16)
    rows[16] = ('>', '', 'sll $v0, $v0, 2')
    [(family, fixed)] = variants(source, 'f', '', rows, RESOLVE)
    assert family == 'measured_clamped_byte_index'
    assert 'u16 col = x;' in fixed
    assert 'col += (u16)y * 10;' in fixed
    assert 'show(((u8 *)&table)[col], y);' in fixed
    [(family, _)] = variants(source.replace('* 10', '* 12'), 'f', '', rows, RESOLVE)
    assert family == 'measured_byte_table_index'


def test_two_calls_share_the_corrected_byte_buffer_displacement():
    ops = (
        'sll $s1, $s2, 1', 'addu $s1, $s1, $s2', 'sll $s1, $s1, 3',
        'lui $s0, %hi(buffer)', 'addiu $s0, $s0, %lo(buffer)', 'move $a0, $s2', 'jal init',
        'addu $a1, $s1, $s0', 'addiu $s0, $s0, -12',
        'lui $a0, %hi(table)', 'addu $a0, $a0, $s2', 'lbu $a0, %lo(table)($a0)',
        'addu $a1, $s1, $s0', 'jal copy', 'addiu $a2, $zero, 24',
    )
    rows = measured(ops)
    change(rows, 2, 'sll $s1, $s1, 5')
    change(rows, 8, 'addiu $s0, $s0, -48')
    rows.insert(9, ('>', '', 'sll $s2, $s2, 2'))
    change(rows, 10, 'lui $a0, %hi(last)')
    change(rows, 12, 'lbu $a0, %lo(last)($a0)')
    source = '''
extern s32 table;
extern s32 buffer;
void f(s32 index) {
    s32 displacement;
    displacement = index * 24;
    init(index, displacement + &buffer);
    copy(*(&table + index), displacement + (&buffer - 12), 24);
}
'''
    [(_, fixed)] = variants(source, 'f', '', rows, RESOLVE)
    assert '((u8 *)&table)[index]' in fixed
    assert fixed.count('(u8 *)&buffer') == 2
    assert 'extern s32 buffer;' in fixed
    [(_, narrow)] = variants(source.replace('buffer - 12', 'buffer - 13'), 'f', '', rows, RESOLVE)
    assert '(u8 *)&buffer' not in narrow
