from decomprepair.measured_thread_addresses import variants


def test_thread_queue_and_stack_use_resolved_addresses():
    ops = '''
lui $a0, %hi(queue)
addiu $a0, $a0, %lo(queue)
lui $a1, %hi(messages)
addiu $a1, $a1, %lo(messages)
addiu $a2, $zero, 1
sw $ra, 28($sp)
jal make_queue
sw $s0, 24($sp)
lui $s0, %hi(game+16)
addiu $s0, $s0, %lo(game+16)
move $a0, $s0
addiu $a1, $zero, 10
lui $a2, %hi(entry)
addiu $a2, $a2, %lo(entry)
lui $v0, %hi(stack)
addiu $v0, $v0, %lo(stack)
sw $v0, 16($sp)
addiu $v0, $zero, 127
move $a3, $zero
jal make_thread
sw $v0, 20($sp)
jal start
move $a0, $s0
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops] + [(' ', 'nop', 'nop')] * 9
    rows[2] = ('<', ops[2], '')
    rows[14] = ('<', ops[14], '')
    source = '''
extern M2C_UNK state, game;
void f(void) {
    void *thread;
    make_queue((char *)&state + 32, (char *)&state + 40, 1);
    thread = (char *)&game + 16;
    make_thread(thread, 0xA, &entry, 0, (char *)&game + 64, 0x7F);
    start(thread);
}
'''
    addresses = {'state': 100, 'game': 200, 'queue': 132, 'messages': 140, 'stack': 264}
    [(label, fixed)] = variants(source, 'f', '', rows, addresses.get)
    assert label == 'measured_thread_symbol_addresses'
    assert 'extern char messages[];' in fixed and 'extern char stack[];' in fixed
    assert '(char *)&messages' in fixed and '(char *)&stack' in fixed
    assert not variants(source, 'f', '', rows, {**addresses, 'stack': 265}.get)
    assert not variants(source, 'f', 'extern s32 stack;', rows, addresses.get)
