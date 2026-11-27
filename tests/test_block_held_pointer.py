from decomprepair.block_held_pointer import variants

ASM = '''lui        $a0, %hi(D_flags)
addiu      $a0, $a0, %lo(D_flags)
lbu        $v0, 0x0($a0)
ori        $v0, $v0, 0x4
sb         $v0, 0x0($a0)
lui        $a1, %hi(D_pick)
addiu      $a1, $a1, %lo(D_pick)
lb         $v0, 0x0($a1)
sb         $zero, 0x1($v0)
lb         $v0, 0x0($a1)
'''
SOURCE = '''extern u8 D_flags;
extern s8 D_pick;
extern u8 D_a[];
extern u8 D_b[];
void func(int x) {
    switch (x) {
    case 0:
        func_other();
        D_flags |= 4;
        break;
    case 1:
        D_a[D_pick] = 1;
        D_b[D_pick] = 1;
        break;
    }
}
'''


def test_each_block_and_all_together():
    children = [source for _, source in variants(SOURCE, 'func', ASM)]
    assert len(children) == 3
    combined = children[0]
    assert 'u8 *held_D_flags = &D_flags;\n(*held_D_flags) |= 4;\n}' in combined
    assert 's8 *held_D_pick = &D_pick;\nD_a[(*held_D_pick)] = 1;' in combined
    assert 'D_b[(*held_D_pick)] = 1;\n}' in combined
    assert combined.count('break;') == 2
    assert all(('held_D_flags' in c) != ('held_D_pick' in c) for c in children[1:])


def test_needs_the_target_to_hold_the_address():
    assert variants(SOURCE, 'func', 'lui $v0, %hi(D_flags)\nlbu $v0, %lo(D_flags)($v0)\n') == []


def test_leaves_arrays_and_address_uses_alone():
    assert variants(SOURCE.replace('D_flags |= 4;', 'func_other(&D_flags);'), 'func', ASM.split('lui        $a1')[0]) == []
