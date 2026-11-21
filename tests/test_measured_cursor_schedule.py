from test_ido_typed_drafts import with_labels

from decomprepair import measured_cursor_schedule as repair


def moved(target, earlier, later, before):
    rows = [(' ', line, line) for line in target]
    line = rows[earlier][1]
    rows[earlier] = ('o', line, '') if before else ('o', '', line)
    rows.insert(later, ('o', '', line) if before else ('o', line, ''))
    return rows


def test_clamp_stays_staged_before_materializing_the_buffer_address():
    rows = [
        (' ', 'jal read', 'jal read'),
        (' ', 'nop', 'nop'),
        ('o', '', 'addiu $a0, $sp, 0x20'),
        (' ', 'nor $v1, $zero, $v0', 'nor $v1, $zero, $v0'),
        (' ', 'sra $v1, $v1, 0x1f', 'sra $v1, $v1, 0x1f'),
        (' ', 'and $v0, $v0, $v1', 'and $v0, $v0, $v1'),
        ('o', 'addiu $a0, $sp, 0x20', ''),
        (' ', 'lui $a1, %hi(fmt)', 'lui $a1, %hi(fmt)'),
        (' ', 'addiu $a1, $a1, %lo(fmt)', 'addiu $a1, $a1, %lo(fmt)'),
        (' ', 'jal write', 'jal write'),
        (' ', 'andi $a2, $v0, 0xffff', 'andi $a2, $v0, 0xffff'),
    ]
    source = '''
void stage(void) {
    s32 value;
    u8 buffer;
    value = read();
    write(&buffer, &fmt, value & ((s32) ~value >> 0x1F) & 0xFFFF);
}
'''
    [(family, fixed)] = repair.variants(source, 'stage', '', rows)
    assert family == 'staged_call_clamp'
    assert 'value &= (s32) ~value >> 31;' in fixed
    assert 'write(&buffer, &fmt, value & 0xFFFF);' in fixed
    assert not repair.variants(source.replace('\n}', '\n    keep(value);\n}'), 'stage', '', rows)


def test_target_context_store_and_flag_are_before_the_source_reload():
    rows = moved([
        'jal enter', 'move $s0, $a0', 'lui $a0, %hi(state)', 'lw $a0, %lo(state)($a0)',
        'sw $s0, 8($a0)', 'lw $a1, 8($a0)', 'addiu $v1, $zero, 1', 'sh $v1, ($a0)',
        'lw $v1, 4($a1)', 'sw $v1, 0xc($a0)', 'jal leave', 'move $a0, $v0',
    ], 4, 7, True)
    source = '''
void configure(void *mode) {
    s32 key;
    void *selected;
    key = enter();
    selected = ((State*)state)->field_8;
    ((State*)state)->field_8 = mode;
    ((State*)state)->field_0 = 1;
    ((State*)state)->field_C = (s32) M2C_FIELD(selected, s32 *, 4);
    leave(key, selected);
}
'''
    [(family, fixed)] = repair.variants(source, 'configure', '', rows)
    assert family == 'context_slot_reload'
    assert fixed.index('field_8 = mode') < fixed.index('field_0 = 1') < fixed.index('selected =')
    assert not repair.variants(source.replace('field_8 = mode', 'field_4 = mode'), 'configure', '', rows)


def test_cursor_pair_uses_byte_units_and_two_separate_increments():
    asm = with_labels(repair._RECORD)
    rows = [('r', 'addiu $a0, $a1, 8', 'addiu $a0, $t0, 8')] * 9
    source = '''
void put(void *root, s32 page, s32 key, s32 value) {
    char *cursor; s32 i; void *entry; void *dest;
    entry = M2C_FIELD(root, s32 *, 0x10) + ((page & 0xFFFF) * 0x14);
    cursor = M2C_FIELD(entry, s32 **, 4);
    i = 0;
    if (M2C_FIELD(entry, u8 *, 0xF) != 0) {
        dest = (void *)(cursor); dest = (void *)((char *)dest + (s32)(8));
scan:
        if (*(s32 *)cursor != key) { i += 1; goto next; }
        if (M2C_FIELD(dest, s8 *, -4) == 0) {
            M2C_FIELD(dest, s32 *, 0) = value;
        } else {
            i += 1;
next:
            cursor += 0xC; dest += 0xC;
            if ((u32) (i & 0xFFFF) >= (u8) M2C_FIELD(entry, u8 *, 0xF)) {
            } else { goto scan; }
        }
    }
}
'''
    [(family, fixed)] = repair.variants(source, 'put', '', rows, asm)
    assert family == 'paired_record_cursor'
    assert fixed.count('__repair_cursor_index += 1;') == 2
    assert '__repair_cursor_value += 12;' in fixed
    assert not repair.variants(source, 'put', '', rows, asm.replace('lb $v0, -4', 'lbu $v0, -4'))


def test_masked_list_separates_entry_key_from_the_loop_counter():
    asm = repair._LIST.pattern.replace('\\', '')
    for key, generic, value in (
        ('sym', 'w+', 'state'), ('global', 'd+', '64'), ('head', 'd+', '24'),
        ('flags', 'd+', '12'), ('bit', 'd+', '8'), ('next', 'd+', '4'),
    ):
        asm = asm.replace(f'(?P<{key}>{generic})', value).replace(f'(?P={key})', value)
    asm = with_labels(asm)
    rows = [('r', 'lw $v1, ($v0)', 'lw $a2, ($v0)')] * 8 + [('i', 'bnez $v1, 28', 'bnez $a2, 24')]
    source = '''
void flag(s32 key) {
    s32 i; void *node;
    node = *M2C_FIELD(M2C_FIELD(&state, void **, 64), void ***, 24);
    i = 0;
    if (node != NULL) {
loop:
        if ((i & 0xFF) == (key & 0xFF)) {
            M2C_FIELD(node, s32 *, 12) = (s32) (M2C_FIELD(node, s32 *, 12) | 8);
            return;
        }
        node = M2C_FIELD(node, void **, 4);
        i += 1;
        if (node == NULL) { } else { goto loop; }
    }
}
'''
    [(family, fixed)] = repair.variants(source, 'flag', '', rows, asm)
    assert family == 'masked_list_cursor'
    assert '__repair_cursor_key = key & 0xFF;' in fixed
    assert fixed.index('if (node != NULL)') < fixed.index('__repair_cursor_key =')
    assert not repair.variants(source.replace('| 8', '| 16'), 'flag', '', rows, asm)
