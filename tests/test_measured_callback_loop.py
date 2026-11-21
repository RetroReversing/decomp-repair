from decomprepair.measured_callback_loop import applies, rewrite

ASM = '''
move $s1, $a0
lui $s0, %hi(pool + 0x10)
addiu $s0, $s0, %lo(pool + 0x10)
lui $s2, %hi(vectors + 0x20)
addiu $s2, $s2, %lo(vectors + 0x20)
lui $s3, %hi(pool + 0x2000)
addiu $s3, $s3, %lo(pool + 0x2000)
addiu $a0, $s1, 4
.Lagain:
addiu $a1, $sp, 0x14
jal receive
nop
lhu $v0, 2($s1)
lw $a0, 0x14($sp)
sll $v0, $v0, 2
addu $v0, $v0, $s2
lw $v0, 0($v0)
jalr $v0
nop
lw $a0, 0x14($sp)
sw $a0, 12($s0)
jal send
sw $s3, 8($a0)
j .Lagain
addiu $a0, $s1, 4
'''

SOURCE = '''
extern M2C_UNK pool;
extern M2C_UNK vectors;
void dispatch(void *q) {
    void *task;
    void *state;
    void *handlers;
    void *next;
    state = &pool + 0x10;
    handlers = &vectors + 0x20;
    next = q + 4;
again:
    receive(next, &task, 1);
    *((M2C_FIELD(q, u16 *, 2) * 4) + handlers)(task);
    M2C_FIELD(state, void **, 12) = task;
    M2C_FIELD(task, void **, 8) = (void *) (&pool + 0x2000);
    send(task);
    next = q + 4;
    goto again;
}
'''

resolve = {'pool': 0x80010000, 'vectors': 0x80020000, 'D_80012000': 0x80012000}.get


def test_reconstructs_callback_index_loop_and_resident_address():
    assert applies(ASM)
    text = rewrite(SOURCE, 'dispatch', ASM, '', resolve)
    assert 'for (;;) {' in text
    assert 'receive(q + 4, &task, 1);' in text
    assert '(*(void (**)(void *))((u8 *)handlers + M2C_FIELD(q, u16 *, 2) * 4))(task);' in text
    assert 'handlers = ((u8 *)&vectors + 0x20);' in text
    assert '__m2c_callback_resident = (u8 *)&D_80012000;' in text
    assert 'M2C_FIELD(task, void **, 8) = __m2c_callback_resident;' in text


def test_requires_matching_index_backedge_and_stack_record_binding():
    assert not rewrite(SOURCE, 'dispatch', ASM.replace('sll $v0, $v0, 2','sll $v0, $v0, 3'), '', resolve)
    assert not rewrite(SOURCE, 'dispatch', ASM.replace('4\n.Lagain','8\n.Lagain'), '', resolve)
    assert not rewrite(SOURCE, 'dispatch', ASM.replace('jal send\nsw $s3','jal send\nsw $s2'), '', resolve)
    assert not rewrite(SOURCE.replace('    send(task);','    send(next);'), 'dispatch', ASM, '', resolve)
    assert not rewrite(SOURCE, 'dispatch', ASM, 'extern u8 pool[];', resolve)
    assert not rewrite(SOURCE, 'dispatch', ASM)
