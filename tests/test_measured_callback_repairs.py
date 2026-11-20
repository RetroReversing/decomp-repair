from decomprepair.measured_callback_repairs import variants

SOURCE = '''
void f(void *owner) {
    void *record;
    void (*callback)(void *);
    cleanup(owner);
    record = M2C_FIELD(owner, void **, 0x10);
    if (record != NULL) {
        callback = M2C_FIELD(record, void (**)(void *), 0xC);
        if (callback != NULL) callback(record);
    }
}
'''


def same(text):
    return ' ',text,text


ROWS = [
    same('jal cleanup'), same('nop'), same('lw $v0, ($s0)'),
    ('r','lw $v1, 0x10($v0)','lw $a0, 0x10($v0)'),
    ('r','beqz $v1, out','beqz $a0, out'),
    same('nop'),
    ('r','lw $v0, 0xc($v1)','lw $v0, 0xc($a0)'),
    same('beqz $v0, out'),same('nop'),same('jalr $v0'),same('nop'),
]


def test_candidate_local_callback_drops_only_the_record_argument():
    expected = SOURCE.replace('(void *)','(void)').replace('callback(record)','callback()')
    assert variants(SOURCE,'f',ROWS) == [('measured_callback_without_record',expected)]
    assert not variants(SOURCE,'f',ROWS[:1]+[same('move $a0, $s0')]+ROWS[2:])
    assert not variants(SOURCE,'f',ROWS[:-1]+[same('move $a1, $s0')])
    assert not variants(SOURCE,'f',ROWS[1:])
    assert not variants(SOURCE,'f',ROWS[:4]+[('r','beqz $v1, else','beqz $a0, out')]+ROWS[5:])


def test_unknown_field_or_escaping_callback_is_left_alone():
    assert not variants(SOURCE.replace('0xC','0xD'), 'f',ROWS)
    assert not variants(SOURCE.replace('0x10','0x14'), 'f',ROWS)
    assert not variants(SOURCE.replace('callback(record);','callback(record); publish(callback);'), 'f',ROWS)
    assert not variants(SOURCE.replace('callback(record);','callback(other);'), 'f',ROWS)
