from decomprepair.measured_kmc_call_stores import variants


def measured(ops):
    return [(' ', op, op) for op in ops]


def test_stage_call_input_before_publishing_its_record():
    rows = measured((*('nop',) * 4, 'lw $a0, 60($s0)', 'lui $at, %hi(published)',
                     'sw $s0, %lo(published)($at)', 'jal send', 'nop', 'move $v0, $s0',
                     *('nop',) * 4))
    rows[4] = ('o', rows[4][1], '')
    rows[8] = ('o', rows[8][1], 'lw $a0, 60($s0)')
    source = '''
void *f(void *entry) {
    M2C_FIELD(&ctx, void **, 32) = entry;
    send(M2C_FIELD(entry, s32 *, 60));
    return entry;
}
'''
    addr = {'ctx': 0x80001000, 'published': 0x80001020}.get
    [(family, fixed)] = variants(source, 'f', '', rows, addr)
    assert family == 'measured_load_before_publishing_pointer'
    assert fixed.index('M2C_FIELD(entry') < fixed.index('M2C_FIELD(&ctx')
    assert 'send(__repair_publish_field);' in fixed
    assert not variants(source, 'f', '', rows)
    assert not variants(source.replace('32)', '28)'), 'f', '', rows, addr)


def test_stage_literal_in_the_halfword_call_delay_slot():
    rows = measured((
        *('nop',) * 4, 'lui $v1, %hi(state)', 'lw $v1, %lo(state)($v1)',
        'lui $a0, %hi(queue)', 'addiu $a0, $a0, %lo(queue)', 'addiu $a1, $zero, 5',
        'move $s0, $v0', 'jal send', 'sh $a1, 20($v1)', 'jal restore', 'move $a0, $s0',
        *('nop',) * 4,
    ))
    rows.insert(10, ('o', '', 'sh $a1, 20($v1)'))
    rows[12] = ('o', rows[12][1], 'addiu $a1, $zero, 5')
    source = '''
void f(void) {
    s32 saved;
    saved = mask();
    M2C_FIELD(state, s16 *, 20) = 5;
    send(&queue, 5);
    restore(saved);
}
'''
    [(family, fixed)] = variants(source, 'f', '', rows)
    assert family == 'measured_staged_call_halfword'
    assert '__repair_call_halfword = 5;' in fixed
    assert 'M2C_FIELD(state, s16 *, 20) = __repair_call_halfword;' in fixed
    assert 'send(&queue, 5);' in fixed
    assert not variants(source.replace('send(&queue, 5)', 'send(&queue, 6)'), 'f', '', rows)
