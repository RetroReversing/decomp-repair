from decomprepair.global_pointer_local_repairs import rewrite_linked_insert


def test_link_insertion_keeps_the_base_and_reads_the_previous_head():
    asm = '''lui $v1, %hi(pool)
lw $v1, %lo(pool)($v1)
lw $v0, 0x18($v1)
sw $v0, ($a0)
jr $ra
sw $a0, 0x18($v1)
'''
    source = '''extern void *pool;
void add_link(M2C_UNK *node) {
    M2C_FIELD(pool, M2C_UNK **, 24) = node;
    *node = M2C_FIELD(pool, M2C_UNK **, 24);
}
'''
    fixed = rewrite_linked_insert(source, 'add_link', asm)
    assert fixed
    field = 'M2C_FIELD(__repair_link_base, M2C_UNK **, 24)'
    assert f'__repair_link_base = pool;\n    *node = {field};\n    {field} = node;' in fixed
    assert rewrite_linked_insert(source, 'add_link', asm.replace('sw $a0, 0x18', 'sw $a0, 0x1C')) is None
    assert rewrite_linked_insert(source.replace('24);', '20);'), 'add_link', asm) is None


def test_transfer_preserves_the_node_until_the_second_call_returns():
    from decomprepair.global_pointer_local_repairs import rewrite_list_transfer

    asm = '''
addiu $sp, $sp, -32
sw $s1, 20($sp)
move $s1, $a0
sw $ra, 24($sp)
sw $s0, 16($sp)
lw $s0, 12($s1)
beqz $s0, .Lexit
nop
.Lloop:
jal unlink
move $a0, $s0
move $a0, $s0
jal link
addiu $a1, $s1, 4
lw $s0, 12($s1)
bnez $s0, .Lloop
nop
.Lexit:
lw $ra, 24($sp)
lw $s1, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 32
'''
    source = '''
void transfer(void *lists) {
    if (M2C_FIELD(lists, s32 *, 0xC) != 0) {
        do {
            unlink(M2C_FIELD(lists, s32 *, 0xC));
            link(M2C_FIELD(lists, s32 *, 0xC), lists + 4);
        } while (M2C_FIELD(lists, s32 *, 0xC) != 0);
    }
}
'''
    fixed = rewrite_list_transfer(source, 'transfer', asm)
    assert fixed
    assert 'unlink(__repair_transfer_node);\n        link(__repair_transfer_node, lists + 4);' in fixed
    assert 'link(__repair_transfer_node, lists + 4);\n        __repair_transfer_node =' in fixed
    assert rewrite_list_transfer(source, 'transfer', asm.replace('move $a0, $s0', 'move $a0, $v0', 1)) is None
    assert rewrite_list_transfer(source.replace('lists + 4', 'lists + 8'), 'transfer', asm) is None
