from decomprepair.measured_kmc_message_thread import variants

SOURCE = '''void f(void) {
    M2C_UNK client;
    M2C_UNK messages;
    s32 message;
    s32 (*callback)(s32);
    void *node;
    create(&queue, &messages, 8);
    add(&client, &queue, 3);
loop:
    receive(&queue, &message, 1);
    node = head;
    if (node == NULL) { goto loop; }
    do {
        callback = M2C_FIELD(node, s32 (**)(s32), 4);
        if ((callback != NULL) && (callback(message) != 0)) { goto loop; }
        node = M2C_FIELD(node, void **, 0);
    } while (node != NULL);
    goto loop;
}'''
ROWS = [(' ', 'nop', 'nop')] * 22 + [
    ('s', 'addiu $sp, $sp, -80', 'addiu $sp, $sp, -40'),
    ('s', 'addiu $a1, $sp, 32', 'addiu $a1, $sp, 16'),
    (' ', 'sw $ra, 76($sp)', 'sw $ra, 36($sp)'),
    (' ', 'jal create', 'jal create'), (' ', 'addiu $a2, $zero, 8', 'addiu $a2, $zero, 8'),
    (' ', 'addiu $a0, $sp, 16', 'addiu $a0, $sp, 20'), (' ', 'move $a1, $s0', 'move $a1, $s0'),
    (' ', 'jal add', 'jal add'), (' ', 'addiu $a2, $zero, 3', 'addiu $a2, $zero, 3'),
    ('s', 'addiu $a1, $sp, 64', 'addiu $a1, $sp, 24'), (' ', 'jal receive', 'jal receive'),
    (' ', 'addiu $a2, $zero, 1', 'addiu $a2, $zero, 1'),
    (' ', 'bnez $s0, 88', 'beqz $s0, 52'), (' ', 'nop', 'nop'),
    (' ', 'j f+52', 'j f+88'), (' ', 'nop', 'nop')]


def test_recovers_stack_arrays_and_loop():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_message_thread_stack_and_loop'
    assert 'M2C_UNK client[4];' in fixed
    assert 'M2C_UNK messages[8];' in fixed
    assert 'create(&queue, messages, 8);' in fixed
    assert 'for (;;) {' in fixed
    assert 'while (node != NULL) {' in fixed


def test_requires_stack_evidence_and_callback_flow():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('&messages, 8', '&messages, 7'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('callback(message) != 0', 'callback(message) == 0'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *node;', 'volatile void *node;'), 'f', '', ROWS)
