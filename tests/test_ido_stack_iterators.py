from decomprepair import draft_call_recovery, ido_stack_iterators

SCAN = '''
void f(void) {
    M2C_UNK sp60;
    M2C_UNK sp3C;
    M2C_UNK sp30;
    Record *slot;
    s32 next;
    s32 cursor;
    cursor = requests;
    if (*cursor != 0) {
        do {
            begin(&sp60, (void *) cursor);
            if (read_next(&sp60, &sp30) != 0) {
                do {
                    if (sp34 >= 0) {
                        slot = &(&table)[sp34];
                        copy_name(&slot->data[0x42], &sp3C);
                        M2C_FIELD(slot, s32 *, 0x60) = sp64;
                    }
                    step(&sp60);
                } while (read_next(&sp60, &sp30) != 0);
            }
            next = M2C_FIELD(cursor, s32 *, 0x18);
            cursor += 0x18;
        } while (next != 0);
    }
}
'''

LOOKUP = '''
s32 f(u8 *out, s32 key) {
    M2C_UNK sp60;
    M2C_UNK sp3C;
    M2C_UNK sp30;
    s32 *address;
    s32 item;
    s32 next;
    s32 cursor;
    s32 i;
    u8 *dst;
    u8 ch;
    u8 last;
    address = &cache[key];
    item = *address;
    cursor = requests;
    if (item != 0) {
        ch = M2C_FIELD(item, u8 *, 0x42);
        i = 0;
        *out = ch;
        if (ch != 0) {
            dst = out;
            do {
                i += 1;
                dst += 1;
                last = M2C_FIELD((*address + i), u8 *, 0x42);
                *dst = last;
            } while (last != 0);
        }
        return 4;
    }
    if (*cursor != 0) {
loop_2:
        begin(&sp60, (void *) cursor);
        if (read_next(&sp60, &sp30) != 0) {
loop_3:
            if (sp34 == key) {
                copy_name(out, &sp3C);
                return 2;
            }
            if (step(&sp60) < 0) {
                return failed;
            }
            if (read_next(&sp60, &sp30) == 0) {
                goto block_4;
            }
            goto loop_3;
        }
block_4:
        close_iter(&sp60);
        next = M2C_FIELD(cursor, s32 *, 0x18);
        cursor += 0x18;
        if (next == 0) {
            goto block_5;
        }
        goto loop_2;
    }
block_5:
    return 0;
}
'''

PREFIX = '''
addiu $sp, $sp, -0x88
lui $s3, %hi(requests)
lw $s3, %lo(requests)($s3)
lw $t0, 0($s3)
addiu $s5, $sp, 0x3C
addiu $s1, $sp, 0x30
addiu $s0, $sp, 0x60
or $a0, $s0, $zero
jal begin
or $a1, $s3, $zero
or $a0, $s0, $zero
jal read_next
or $a1, $s1, $zero
lw $t0, 0x34($sp)
'''
SCAN_ROWS = '''
jal copy_name
addiu $a0, $s2, 0x42
lw $t2, 0x64($sp)
sw $t2, 0x60($s2)
'''
LOOKUP_ROWS = '''
lbu $v0, 0x42($a3)
lbu $v0, 0x42($t0)
jal copy_name
addiu $a1, $sp, 0x3C
jal close_iter
or $a0, $s0, $zero
'''
SUFFIX = '''
jal step
or $a0, $s0, $zero
lw $t3, 0x18($s3)
addiu $s3, $s3, 0x18
bnel $t3, $zero, {target}
or $a0, $s0, $zero
nop
nop
nop
nop
nop
nop
jr $ra
addiu $sp, $sp, 0x88
'''


def asm(rows, branch_shift=0):
    pc = 0x80400000
    ops = [row for row in (PREFIX + rows + SUFFIX).splitlines() if row]
    entry = ops.index('jal begin')
    result = []
    for i, row in enumerate(ops):
        word = 0
        if '{target}' in row:
            word = 0x55600000 | ((entry + branch_shift - i - 1) & 0xFFFF)
            row = row.format(target=f'.L{pc + 4 * entry:08X}')
        result.append(f'/* {4 * i:04X} {pc + 4 * i:08X} {word:08X} */ {row}')
    return '\n'.join(result)


def test_scan_uses_the_witnessed_record_stack_offsets_and_stride():
    target = asm(SCAN_ROWS)
    [(family, result)] = draft_call_recovery.variants(SCAN, 'f', target, '', 'ido-7.1')
    assert family == ido_stack_iterators.FAMILY
    assert 'u8 rest[20]; } *cursor;' in result
    assert 'u8 _m2c_iter_scratch[36];' in result
    assert 'while (read_next((void *)&_m2c_iter_state, (void *)&_m2c_iter_record) != 0)' in result
    assert 'M2C_FIELD(slot, s32 *, 0x60) = _m2c_iter_state.word;' in result
    assert not ido_stack_iterators.applies(asm(SCAN_ROWS, branch_shift=1))
    assert not ido_stack_iterators.rewrite(SCAN.replace('cursor += 0x18;', 'cursor += 24;'), 'f', target)
    assert not ido_stack_iterators.rewrite(SCAN, 'f', target, 'extern int sp64;')


def test_lookup_keeps_the_reload_in_the_byte_loop_and_closes_each_iterator():
    target = asm(LOOKUP_ROWS)
    result = ido_stack_iterators.rewrite(LOOKUP, 'f', target)
    assert 'u8 name[28]' in result
    assert '((u8 *)cache[key])[i + 0x42]' in result
    assert '_m2c_iter_record.index == key' in result
    assert 'close_iter((void *)&_m2c_iter_state);' in result
    assert 'goto' not in result
    assert not ido_stack_iterators.rewrite(LOOKUP, 'f', target.replace('0x3C\n', '0x40\n'))
