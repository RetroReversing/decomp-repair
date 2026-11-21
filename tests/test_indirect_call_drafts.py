from decomprepair.indirect_call_drafts import applies, rewrite

TABLE = '''
lhu $v0, 6($s0)
sll $v0, $v0, 2
lui $at, %hi(handlers)
addu $at, $at, $v0
lw $v0, %lo(handlers)($at)
jalr $v0
move $a0, $s0
'''
SOURCE = '''
extern M2C_UNK handlers;

void f(void *entry) {
    do {
        *(&handlers + (M2C_FIELD(entry, u16 *, 6) * 4))(entry);
    } while (ready);
}
'''


def test_indirect_call_stages_the_word_index_proven_by_the_delay_slot():
    assert applies(TABLE)
    fixed = rewrite(SOURCE, 'f', TABLE)
    assert 'u32 __repair_dispatch_offset = (M2C_FIELD(entry, u16 *, 6) * 4);' in fixed
    assert '(*(void (**)())((char *)&handlers + __repair_dispatch_offset))(entry);' in fixed
    assert 'u32 __repair_dispatch_offset' not in rewrite(SOURCE, 'f', TABLE.replace('6($s0)', '8($s0)'))
    assert rewrite(SOURCE, 'f', TABLE.replace('jalr $v0', 'jalr $v1')) is None
    assert rewrite(SOURCE.replace('handlers +', 'other +'), 'f', TABLE) is None
    assert rewrite(SOURCE.replace('* 4)', '* 8)'), 'f', TABLE) is None
    assert rewrite(SOURCE, 'f', TABLE + '\njalr $t0\nnop') is None


def test_indirect_call_preserves_the_draft_destination_type_and_byte_address():
    source = '''
extern M2C_UNK table;
void *f(s32 n) {
    void *result;
    result = *(s32 *)(&table + 32 + (n * 4))(n);
    return result;
}
'''
    symbols = {'table': 0x100, 'handlers': 0x120}
    fixed = rewrite(source, 'f', TABLE, resolve=symbols.get)
    assert 'result = (*(void * (**)())((char *)&table + 0x20 + (n * 4)))(n);' in fixed
    assert rewrite(source, 'f', TABLE) is None
    assert rewrite(source.replace('+ 32', '+ 36'), 'f', TABLE, resolve=symbols.get) is None


QUEUE_SETUP = '''
addiu $sp, $sp, -0x20
sw $s0, 0x18($sp)
move $s0, $a0
sw $ra, 0x1c($sp)
addiu $a0, $s0, 0x14
addiu $a1, $sp, 0x10
jal receive
addiu $a2, $zero, 1
'''
QUEUE_LOOP = '''
.Lend:
j .Lend
nop
lw $ra, 0x1c($sp)
jr $ra
addiu $sp, $sp, 0x20
'''
QUEUE_SOURCE = '''
void f(void *obj) {
    M2C_UNK sp10;
    receive(obj + 0x14, &sp10, 1);
    *(&handlers + (M2C_FIELD(obj, u16 *, 6) * 4))();
loop:
    goto loop;
}
'''


def test_terminal_queue_inserts_boundary_only_for_observed_return_address_order():
    asm = QUEUE_SETUP + TABLE.replace('move $a0, $s0', 'nop') + QUEUE_LOOP
    fixed = rewrite(QUEUE_SOURCE, 'f', asm)
    assert 'do { } while (0);\n    receive(' in fixed
    assert '(*(void (**)())((char *)&handlers + (M2C_FIELD(obj, u16 *, 6) * 4)))();' in fixed
    assert 'do { }' not in rewrite(QUEUE_SOURCE, 'f', asm.replace('0x14', '0x18'))


def test_queue_keeps_proven_loop_invariant_table_base_resident():
    source = '''
void f(void *obj) {
    M2C_UNK sp10;
    void *queue;
    queue = obj + 0x14;
loop:
    receive(queue, &sp10, 1);
    *((M2C_FIELD(obj, u16 *, 6) * 4) + (&state + 0x40))();
    send(obj, &sp10);
    queue = obj + 0x14;
    goto loop;
}
'''
    asm = '''
addiu $sp, $sp, -40
sw $s0, 24($sp)
move $s0, $a0
sw $s1, 28($sp)
lui $s1, %hi(state + 0x40)
addiu $s1, $s1, %lo(state + 0x40)
sw $ra, 32($sp)
addiu $a0, $s0, 0x14
.Lloop:
addiu $a1, $sp, 16
jal receive
addiu $a2, $zero, 1
lhu $v0, 6($s0)
sll $v0, $v0, 2
addu $v0, $v0, $s1
lw $v0, ($v0)
jalr $v0
nop
jal send
nop
j .Lloop
addiu $a0, $s0, 0x14
'''
    fixed = rewrite(source, 'f', asm)
    assert '__repair_dispatch_table = (char *)&state + 0x40;\n    do { } while (0);' in fixed
    assert '(*(void (**)())(__repair_dispatch_table + (M2C_FIELD(obj, u16 *, 6) * 4)))();' in fixed
    assert '__repair_dispatch_table' not in rewrite(source, 'f', asm.replace('j .Lloop', 'j .Lelse'))
    assert not applies(asm.replace('.Lloop:\n', '.Lloop:\nmove $s1, $a0\n'))
