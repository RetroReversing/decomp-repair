from decomprepair import arm_constant_fence_local

SOURCE = '''void func(void *obj, s32 ready) {
    void *part;

    if (ready) {
        *(u8 *)((char *)(obj) + 0x71) = 0x80;
        *(u16 *)((char *)(obj) + 0x10) = 0x2000U;
        part = spawn();
        *(u16 *)((char *)(part) + 0x10) = 0x2000;
    }
}
'''


def test_fence_at_the_block_head_and_every_store_reads_the_local():
    children = arm_constant_fence_local.variants(SOURCE, 'func')
    family, child = children[0]
    assert family == 'arm_constant_fence_local'
    assert 'u16 size;' in child
    assert 'if (ready) {\n        do { size = 0x2000; } while (0);\n' in child
    assert child.count('= size;') == 2
    assert '0x2000U' not in child and '= 0x80;' in child


def test_a_constant_with_no_call_between_its_stores_declines():
    flat = SOURCE.replace('        part = spawn();\n', '')
    assert arm_constant_fence_local.variants(flat, 'func') == []


def test_a_comparison_is_not_a_store():
    compared = SOURCE.replace('*(u16 *)((char *)(part) + 0x10) = 0x2000;', 'spawn(part == 0x2000);')
    assert arm_constant_fence_local.variants(compared, 'func') == []
