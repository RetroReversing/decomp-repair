from decomprepair import dead_operand_accumulate, fill_extent_locals, stack_array_access_width

DRAFT = """extern s32 D_800A0000;
extern char D_800A1000[];

void run(s16 id) {
    u8 sp10[0x8C];
    s32 *sp98;
    s32 sp9C;
    u8 spA8[0x8C];
    s32 *sp130;
    s32 base;
    s32 size;
    s32 dest;

    memSet(sp10, 0, 0x98);
    base = D_800A0000;
    sp98 = D_800A1000;
    sp9C = 0x788;
    memSet(spA8, 0, 0x98);
    sp130 = D_800A1000;
    size = *(spA8 + (id * 8)) * 0x10;
    dest = ((u32) (base + size + 0xF) >> 4) * 0x10;
    copy(dest, *(sp10 + (id * 8)));
}
"""
ASM = "lw $a1, 0($v0)\nsw $a1, 4($s1)\n"


def kids(module, source, family=None, **extra):
    return [c for f, c in module.variants(source, 'run', **extra) if family in (None, f)]


def test_locals_inside_a_fill_become_members_of_the_array():
    child = kids(fill_extent_locals, DRAFT, 'fill_extent_locals')[0]
    assert 'u8 sp10[0x98];' in child and 'u8 spA8[0x98];' in child
    assert 's32 *sp98;' not in child and 'sp9C;' not in child and 'sp130;' not in child
    assert '(*(s32 **)&sp10[0x88]) = D_800A1000;' in child
    assert '(*(s32 *)&sp10[0x8C]) = 0x788;' in child
    assert '(*(s32 **)&spA8[0x88]) = D_800A1000;' in child


def test_a_fill_that_fits_its_array_is_left_alone():
    assert not kids(fill_extent_locals, DRAFT.replace('0x98);', '0x8C);'), 'fill_extent_locals')


def test_a_global_read_moves_above_the_fill_but_an_address_does_not():
    moved = kids(fill_extent_locals, DRAFT, 'global_read_above_fill')
    assert len(moved) == 1
    assert 'base = D_800A0000;\n    memSet(sp10, 0, 0x98);' in moved[0]


def test_a_byte_array_access_takes_the_width_the_target_loads():
    wide = kids(stack_array_access_width, DRAFT, asm=ASM)
    assert any('*(s32 *)(sp10 + (id * 8))' in c for c in wide)
    assert any('*(s32 *)(spA8 + (id * 8)) * 0x10' in c for c in wide)
    assert not kids(stack_array_access_width, DRAFT, asm='lbu $a1, 0($v0)\n')


def test_a_dead_operand_is_advanced_in_place():
    child = kids(dead_operand_accumulate, DRAFT)[0]
    assert 'base += size;\n    dest = ((u32) (base + 0xF) >> 4) * 0x10;' in child


def test_an_operand_read_later_or_in_a_loop_is_not_advanced():
    assert not kids(dead_operand_accumulate, DRAFT.replace('copy(dest,', 'copy(base,'))
    assert not kids(dead_operand_accumulate, DRAFT.replace('    copy(', '    while (id) { id--; }\n    copy('))
