from decomprepair.measured_record_ramp import variants

SOURCE = '''void update(void *owner) {
    s32 slot;
    s32 displacement;
    s32 step;
    s32 counter;
    s32 scaled;
    u16 count;
    short level;
    void *table;
    table = M2C_FIELD(owner, void **, 0x78);
    count = M2C_FIELD(owner, u16 *, 0x88);
    level = M2C_FIELD(table, u8 *, 0x14);
    step = (s32) (M2C_FIELD(table, u8 *, 0x17) - level) / (s32) (count - 1);
    counter = 0;
    if (count != 0) {
        scaled = level * 5;
        rows: {
            slot = counter & 0xFFFF;
            displacement = slot * 0xC;
            write_item(owner, slot, (s16) level, M2C_FIELD(M2C_FIELD(owner, void **, 0x78), s32 *, 0x1C) + displacement + 6);
            counter += 1;
            M2C_FIELD((displacement + M2C_FIELD(M2C_FIELD(owner, void **, 0x78), s32 *, 0x1C)), s16 *, 4) = (s16) (scaled * 2);
            scaled += step * 5;
            level += step;
        }
        if ((u32) (counter & 0xFFFF) < (u16) M2C_FIELD(owner, u16 *, 0x88)) goto rows;
    }
}'''
T = ['lw $v0, 0x78($s2)', 'lhu $a1, 0x88($s2)', 'lbu $a0, 0x14($v0)', 'lbu $v1, 0x17($v0)',
     'div $zero, $v1, $v0', 'mflo $s5', 'sll $s0, $a1, 1', 'addu $s0, $s0, $a1',
     'sll $s0, $s0, 2', 'lw $a3, 0x1c($v0)', 'jal write_item']
ROWS = [('r', line, '') for line in T]


def test_reconstructs_record_ramp():
    label, candidate = variants(SOURCE, 'update', '', ROWS)[0]
    assert label == 'measured_record_ramp'
    assert 's32 slot, step, counter, scaled, level;' in candidate
    assert '__repair_start = M2C_FIELD(table, u8 *, 0x14);' in candidate
    assert 'slot = counter & 0xFFFF;' in candidate
    assert candidate.index('level += step;') > candidate.index('if ((u32) (counter & 0xFFFF)')


def test_requires_evidence_and_complete_unmodified_body():
    assert not variants(SOURCE, 'update', '', ROWS[:-1])
    assert not variants(SOURCE.replace('counter += 1;', 'counter += 1; observe(owner);'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('short level;', 'volatile short level;'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('short level;', 'short level; /* explanation */'), 'update', '', ROWS)
    assert not variants(SOURCE, 'update', '#define level alias', ROWS)
