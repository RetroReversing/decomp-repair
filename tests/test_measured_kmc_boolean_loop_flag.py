from decomprepair.measured_kmc_boolean_loop_flag import variants

SOURCE = '''void f(void *head) {
    s32 active;
    void *node;
    active = 1;
    node = head;
    do {
        if (test(node)) active = 0;
        node = M2C_FIELD(node, void **, 4);
    } while (active & (node != NULL));
}'''
ROWS = [('|', 'sltu $v0, $zero, $s0', 'beqz $s0, 0x78'),
        ('|', 'and $v0, $s2, $v0', 'andi $v0, $s2, 1')]


def test_uses_byte_flag_and_boolean_operands():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_boolean_loop_flag'
    assert 'u8 active;' in fixed
    assert 'while ((node != NULL) & (active != 0))' in fixed


def test_requires_boolean_only_flag_and_target_evidence():
    assert not variants(SOURCE, 'f', '', ROWS[:1])
    assert not variants(SOURCE.replace('active = 1;', 'active = 2;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('active = 1;', 'active = 1; use(active);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s32 active;', 'volatile s32 active;'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '#define active other', ROWS)
