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
