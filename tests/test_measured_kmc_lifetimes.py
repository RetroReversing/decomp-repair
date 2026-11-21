from decomprepair.measured_kmc_lifetimes import variants


def changed(trace, old=None):
    lines = trace.strip().splitlines()
    return [('r' if i == 3 else ' ', line, old or 'different register' if i == 3 else line)
            for i, line in enumerate(lines)]


def test_narrow_call_result_requires_register_evidence_and_no_conflicting_prototype():
    rows = changed('''
jal reserve
addiu $a1, $zero, 2
lw $v1, 16($s0)
andi $v0, $v0, 0xffff
sll $a0, $v0, 2
addu $v1, $v1, $a0
sw $zero, ($v1)
lw $t0, ($s1)
sll $a0, $v0, 3
addu $t0, $t0, $a0
sw $a2, ($t0)
lw $v1, 4($s1)
sw $a1, ($v1)
lw $ra, 16($sp)
lw $s0, 20($sp)
jr $ra
addiu $sp, $sp, 24
''', 'andi $a0, $v0, 0xffff')
    source = '''
s32 reserve();
void emit(void *ctx) {
    s32 ticket;
    ticket = reserve(ctx, 2) & 65535;
    write_ticket(ctx, ticket);
}
'''
    [(family, fixed)] = variants(source, 'emit', '', rows)
    assert family == 'measured_narrow_call_return'
    assert 's32 emit(void *ctx)' in fixed
    assert 'ticket = (u16)reserve(ctx, 2);' in fixed
    assert 'return ticket;' in fixed
    assert not variants(source, 'emit', 'extern void emit(void *);', rows)
    assert not variants(source.replace('write_ticket', 'ticket <<= 1; write_ticket'), 'emit', '', rows)
    wrong = rows.copy()
    wrong[6] = ('r', 'move $v0, $a0', 'sw $zero, ($v1)')
    assert not variants(source, 'emit', '', wrong)


def test_guarded_pointer_walk_adds_scope_without_moving_the_backedge():
    rows = changed('''
lh $v0, 2($s2)
blez $v0, 64
move $s1, $zero
move $s0, $s2
lw $v0, 24($s0)
addu $a0, $v0, $s3
beqz $a0, 44
sw $a0, 24($s0)
move $a1, $s3
jal fix_row
move $a2, $s4
lh $v0, 2($s2)
addiu $s1, $s1, 1
slt $v0, $s1, $v0
bnez $v0, 16
addiu $s0, $s0, 8
lw $ra, 24($sp)
''')
    source = '''
void relocate(void *base, s32 delta, s32 extra) {
    void *cursor;
    s32 count, address;
    count = 0;
    if (M2C_FIELD(base, s16 *, 2) > 0) {
        cursor = base;
        again: {
            address = M2C_FIELD(cursor, s32 *, 24) + delta;
            M2C_FIELD(cursor, s32 *, 24) = address;
            if (address != 0) {
                fix_row(address, delta, extra);
            }
            count += 1;
            cursor += 8;
        }
        if (count < M2C_FIELD(base, s16 *, 2)) goto again;
    }
}
'''
    [(family, fixed)] = variants(source, 'relocate', '', rows)
    assert family == 'measured_guarded_walk_scope'
    assert fixed.index('do {') < fixed.index('cursor = base;')
    assert fixed.index('goto again;') < fixed.index('} while (0);')
    bad_edge = [('r', left.replace('bnez $v0, 16', 'bnez $v0, 20'), right) for _, left, right in rows]
    assert not variants(source, 'relocate', '', bad_edge)
    assert not variants(source.replace('cursor += 8;', 'cursor += 4;'), 'relocate', '', rows)
    assert not variants(source.replace('count = 0;', 'goto again; count = 0;'), 'relocate', '', rows)


def test_update_paired_counters_keeps_the_late_reloads():
    rows = changed('''
move $t0, $a0
lw $v0, 84($t0)
lw $v1, 96($t0)
lw $a2, 376($v1)
lw $a3, 372($v1)
addu $a3, $a3, $v1
subu $a3, $a3, $v0
addu $a2, $a2, $v1
subu $a2, $a2, $v0
sb $v0, 5($a1)
nop
lw $v0, 96($t0)
sw $a2, 376($v0)
lw $v0, 96($t0)
jr $ra
sw $a3, 372($v0)
''')
    source = '''
void update(void *owner, void *out) {
    s32 total; s32 right; s32 left; s32 p; s32 q; s32 next_right; s32 next_left;
    void *input; void *state;
    input = M2C_FIELD(owner, void **, 0x54);
    state = M2C_FIELD(owner, void **, 0x60);
    right = M2C_FIELD(state, s32 *, 0x178);
    left = M2C_FIELD(state, s32 *, 0x174);
    total = M2C_FIELD(input, s32 *, 0x10) + M2C_FIELD(input, s32 *, 0x14);
    if (total >= 0x5DD) {
        next_left = left + (left < 0xFA);
        p = M2C_FIELD(out, u8 *, 4) - next_left;
        M2C_FIELD(out, u8 *, 4) = (u8) (p & ((s32) ~p >> 0x1F));
    } else {
        next_left = left - (left >= 6);
    }
    if (total < -0x5DC) {
        next_right = right + (right < 0xFA);
        q = M2C_FIELD(out, u8 *, 5) - next_right;
        M2C_FIELD(out, u8 *, 5) = (u8) (q & ((s32) ~q >> 0x1F));
    } else {
        next_right = right - (right >= 6);
    }
    M2C_FIELD(M2C_FIELD(owner, void **, 0x60), s32 *, 0x178) = next_right;
    M2C_FIELD(M2C_FIELD(owner, void **, 0x60), s32 *, 0x174) = next_left;
}
'''
    [(family, fixed)] = variants(source, 'update', '', rows)
    assert family == 'measured_paired_counter_updates'
    assert 'left += (left < 0xFA);' in fixed
    assert 'right -= (right >= 6);' in fixed
    assert 'M2C_FIELD(M2C_FIELD(owner, void **, 0x60), s32 *, 0x178) = right;' in fixed
    assert not variants(source.replace('0x178) = next_right', '0x178) = right'), 'update', '', rows)


def test_slot_paths_share_word_stride_and_keep_mode_reads():
    rows = changed('''
xori $v0, $a1, 6
sltu $v0, $zero, $v0
negu $v0, $v0
and $a1, $a1, $v0
sltiu $v0, $a1, 4
lhu $v1, 14($a2)
lhu $v0, 18($a2)
lw $v1, 24($a0)
sll $v0, $a1, 1
lhu $a2, 14($v1)
lhu $v0, 18($v1)
sll $v0, $a1, 1
lhu $v1, 14($v0)
lw $v0, 24($a0)
sll $v0, $a1, 1
lw $v1, 32($a0)
addu $v0, $v0, $a1
sll $v0, $v0, 2
lui $at, %hi(table_a)
addu $at, $at, $v0
sw $v1, %lo(table_a)($at)
lw $v1, 36($a0)
lui $at, %hi(table_b)
addu $at, $at, $v0
sw $v1, %lo(table_b)($at)
lw $v1, 40($a0)
lui $at, %hi(table_c)
addu $at, $at, $v0
sw $v1, %lo(table_c)($at)
jr $ra
nop
''')
    mode = 'M2C_FIELD(M2C_FIELD(&shared, void **, 128), u16 *, 14)'
    flags = 'M2C_FIELD(M2C_FIELD(&shared, void **, 128), u16 *, 18)'
    kind = 'M2C_FIELD(record, s32 *, 24)'
    scale = 'slot = masked * 2'
    source = f'''
void route(void *record) {{
    s32 slot; s32 offset; u16 mode; u32 masked;
    slot = *M2C_FIELD(M2C_FIELD(&owner, void **, 64), s32 **, 4);
    masked = slot & -(slot != 6);
    if ((masked < 4U) && ((({mode} == 2) && !({flags} & 1) && ({scale}, ({kind} == 3))) ||
        ((mode = {mode}, (mode == {kind})) && ({flags} & 1) && ({scale}, (mode == 2))) ||
        ((mode = {mode}, (mode == 1)) && ({scale}, ({kind} == mode))))) {{
        offset = (slot + masked) * 4;
        *(&table_a + offset) = M2C_FIELD(record, s32 *, 32);
        *(&table_b + offset) = M2C_FIELD(record, s32 *, 36);
        *(&table_c + offset) = M2C_FIELD(record, s32 *, 40);
    }}
}}
'''
    [(family, fixed)] = variants(source, 'route', '', rows)
    assert family == 'measured_slot_record_stride'
    assert 'if ((u32)slot < 4)' in fixed
    assert fixed.count('else if') == 2
    assert fixed.count('*(&table_a + slot * 3)') == 3
    assert fixed.count(mode) == 3
    assert not variants(source.replace('table_c', 'table_d'), 'route', '', rows)
    assert not variants(source.replace('*, 24)', '*, 25)'), 'route', '', rows)
