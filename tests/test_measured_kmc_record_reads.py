from decomprepair.measured_kmc_record_reads import variants


def measured(ops):
    return [(' ', op, op) for op in ops]


def test_capture_flags_before_publishing_the_record():
    pair = ('lui $at, %hi(published)', 'sw $v0, %lo(published)($at)')
    old_new = [
        ('lw $a0, 32($v0)', 'lw $v1, 32($v0)'),
        ('lui $v1, %hi(work)', 'lui $a0, %hi(work)'),
        ('addiu $v1, $v1, %lo(work)', 'addiu $a0, $a0, %lo(work)'),
    ]
    end = [('sw $v1, 40($v0)', 'sw $a0, 40($v0)'), ('ori $a0, $a0, 4', 'ori $v1, $v1, 4'),
           ('sw $a0, 32($v0)', 'sw $v1, 32($v0)')]
    rows = measured(['nop'] * 19)
    rows += [('o', '', x) for x in pair] + [('r', a, b) for a, b in old_new]
    rows += [('o', x, '') for x in pair] + [('r', a, b) for a, b in end]
    source = '''
void f(void *obj) {
    M2C_FIELD(&owner, void **, 28) = obj;
    M2C_FIELD(obj, M2C_UNK **, 40) = &work;
    M2C_FIELD(obj, s32 *, 32) = (s32) (M2C_FIELD(obj, s32 *, 32) | 4);
}
'''
    resolve = {'owner': 0x80000000, 'published': 0x8000001c}.get
    [(family, fixed)] = variants(source, 'f', '', rows, resolve)
    assert family == 'measured_pre_publish_field_read'
    assert fixed.index('flags = M2C_FIELD') < fixed.index('M2C_FIELD(&owner')
    assert not variants(source.replace('28)', '32)'), 'f', '', rows, resolve)


def test_halfword_arguments_use_a_byte_index_and_byte_stride():
    rows = []
    for i in range(4):
        rows += measured((f'lui $v1, %hi(key{i})', f'lbu $v1, %lo(key{i})($v1)', 'sll $v0, $v1, 1',
                          'addu $v0, $v0, $v1'))
        rows += [('i', 'sll $v0, $v0, 2', 'sll $v0, $v0, 4'),
                 ('i', 'lui $a1, %hi(table)', 'lui $a1, %hi(scaled)')]
        rows += measured(('addu $a1, $a1, $v0',))
        rows += [('i', 'lhu $a1, %lo(table)($a1)', 'lhu $a1, %lo(scaled)($a1)')]
        rows += measured(('jal send', 'addiu $a0, $zero, 5'))
    source = 'void f(void) {\n' + ''.join(
        f'    send(5, *(&ctx + 96 + (M2C_FIELD(&ctx, u8 *, {32 + i}) * 12)));\n' for i in range(4)
    ) + '}\n'
    addresses = {'ctx': 0x80000000, 'table': 0x80000060,
                 **{f'key{i}': 0x80000020+i for i in range(4)}}
    [(family, fixed)] = variants(source, 'f', '', rows, addresses.get)
    assert family == 'measured_byte_stride_halfword_calls'
    assert 'extern u8 table[];' in fixed
    assert 'send(5, M2C_FIELD(table, u16 *, key0[3] * 12));' in fixed
    assert not variants(source, 'f', 'extern s32 table;', rows, addresses.get)
    assert not variants(source.replace('* 12', '* 16'), 'f', '', rows, addresses.get)


def test_guarded_call_drops_only_the_inferred_declaration():
    rows = measured(('nop',) * 13)
    rows += measured((
        'sltu $a2, $zero, $v0', 'srl $v0, $a0, 8', 'andi $v0, $v0, 3', 'bne $v0, $v1, 44',
        'move $a1, $a2', 'andi $v0, $a0, 15', 'xor $v0, $v0, $a3', 'sltu $v0, $zero, $v0',
        'negu $v0, $v0', 'and $a1, $a2, $v0', 'andi $v0, $a1, 255', 'bnez $v0, 116', 'nop',
        'lui $at, %hi(flag)', 'sb $zero, %lo(flag)($at)', 'jal notify', 'nop', 'jal flush', 'nop',
    ))
    for j in range(7):
        rows[j] = ('r', rows[j][1], 'different preparatory register')
    rows.insert(14, ('>', '', 'move $a2, $t0'))
    source = '''
M2C_UNK notify(u32, s32, s32, s8);
void f(s32 status, s32 seen, s8 slot) {
    if (!(status & 0xFF)) {
        M2C_FIELD(&publish, s8 *, 4) = 0;
        notify(M2C_FIELD(&state, u32 *, 8), status, seen, slot);
        flush();
    }
}
'''
    resolve = {'publish': 0x80001000, 'flag': 0x80001004}.get
    [(family, fixed)] = variants(source, 'f', '', rows, resolve)
    assert family == 'measured_drop_inferred_guarded_call_args'
    assert 'notify(void);' in fixed and 'notify();' in fixed
    assert not variants(source, 'f', 'void notify(u32, s32, s32, s8);', rows, resolve)
    assert not variants(source.replace('notify(M2C_FIELD', 'other(M2C_FIELD'), 'f', '', rows, resolve)


def test_arm_local_record_bases_keep_each_mask_and_offset():
    rows = measured(['nop'] * 3)
    tail = []
    for i in range(13):
        field = 24 + 4*i
        rows += [
            ('r', 'addu $v0, $v0, $v1', 'addu $v1, $v1, $v0'),
            ('r', f'lw $v0, {field}($v0)', f'lw $v0, {field}($v1)'),
        ]
        tail.append(f'if (bits & {1 << (i+1)}) {{ out |= M2C_FIELD((data + (index * 56)), s32 *, {field}); }}')
    source = '''
extern s32 data;
s32 f(s32 bits, s32 index) {
    char *addr;
    s32 out = 0;
    if (bits & 1) {
        addr = (char *)((data + (index * 56)));
        out = M2C_FIELD(addr, s32 *, 20);
    }
''' + '\n'.join(tail) + '\nreturn out;\n}'
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_guarded_record_bases'
    assert fixed.count('s32 __repair_arm_base = data;') == 14
    assert 'out = M2C_FIELD(__repair_arm_base, s32 *, 20);' in fixed
    assert 'out |= M2C_FIELD(__repair_arm_base, s32 *, 72);' in fixed
    assert not variants(source.replace('s32 *, 24', 's32 *, 25'), 'f', '', rows)
