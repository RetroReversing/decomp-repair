"""A configuration block filled on the stack for a call, rebuilt as one array with its stores in slot order."""
from decomprepair import frame_block_init_order as r

# The shape of an N64 start-up function (synthetic: its own names and constants).
SOURCE = '''void f(void) {
    s32 sp10[2];
    s32 *sp18;
    s32 sp1C[4];
    u32 temp_v0;

    sp10[1] = 0x12;
    do { sp18 = &D_80001000;
    sp1C[0] = 0xC;
    sp1C[3] = 0x40; } while (0);
    sp1C[2] = 0x100;
    sp10[0] = 0;
    D_80002000 = temp_v0;
    temp_v0 = D_80003000 + 0xF;
    sp1C[1] = temp_v0;
    init(sp10);
}
'''

# The frame: the block at 0x10, $ra above it; the target stores 0x28 (slot 6) before 0x24 (slot 5).
ASM = '''addiu $sp, $sp, -0x38
sw $v0, 0x14($sp)
sw $v0, 0x18($sp)
sw $v0, 0x1c($sp)
sw $v0, 0x28($sp)
sw $v0, 0x24($sp)
sw $ra, 0x30($sp)
sw $zero, 0x10($sp)
'''


def test_the_block_is_rebuilt_as_one_child():
    first, *_ = [text for _, text in r.variants(SOURCE, 'f', ASM)]
    assert '    s32 sp10[8];\n' in first
    assert 'do {' not in first and 'sp18' not in first
    body = [line.strip() for line in first.splitlines()]
    assert body[body.index('sp10[0] = 0;'):body.index('init(sp10);')] == [
        'sp10[0] = 0;', 'sp10[1] = 0x12;', 'sp10[2] = (s32) (&D_80001000);', 'sp10[3] = 0xC;',
        'D_80002000 = (temp_v0 = D_80003000 + 0xF);', 'sp10[4] = temp_v0;', 'sp10[6] = 0x40;', 'sp10[5] = 0x100;']


def test_ascending_and_unchained_children_follow():
    found = [text for _, text in r.variants(SOURCE, 'f', ASM)]
    assert len(found) == 4
    plain = found[1]
    assert 'temp_v0 = D_80003000 + 0xF;\n    D_80002000 = temp_v0;\n    sp10[4] = temp_v0;' in plain
    assert found[2].index('sp10[5] = 0x100;') < found[2].index('sp10[6] = 0x40;')


def test_the_array_grows_to_the_saved_register_slot():
    first = r.variants(SOURCE, 'f', ASM.replace('sw $ra, 0x30($sp)', 'sw $ra, 0x38($sp)'))[0][1]
    assert 's32 sp10[10];' in first


def test_left_alone_without_a_block_call_or_with_a_call_inside():
    assert r.variants(SOURCE.replace('init(sp10);', 'init(0);'), 'f', ASM) == []
    assert r.variants(SOURCE.replace('sp10[0] = 0;', 'sp10[0] = g();'), 'f', ASM) == []
    assert r.variants(SOURCE.replace('sp10[0] = 0;', 'if (x) { sp10[0] = 0; }'), 'f', ASM) == []
    assert r.variants(SOURCE, 'f', '') == []
