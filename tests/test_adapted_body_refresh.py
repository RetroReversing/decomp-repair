"""A body copied from a look-alike in another game, brought to this target; the assembly here is made up."""
from decomprepair import adapted_body_refresh as repair
from decomprepair import store_run_order


def _asm(body):
    lines, address = ['glabel serve'], 0x80001000
    for line in body.strip().splitlines():
        line = line.strip()
        if line.startswith('.L'):
            lines.append(f'  {line}')
        else:
            lines.append(f'/* 0 {address:08X} 00000000 */  {line}')
            address += 4
    return '\n'.join(lines) + '\n'


ASM = _asm("""
    lui $s3, (0x80100000 >> 16)
    lui $s5, (0x80100000 >> 16)
.Ltop:
    jal poll
    nop
    bne $v0, $zero, .Lother
    addiu $v1, $v0, -0x4
    jal wait
    addiu $a0, $zero, 0x10
.Lother:
    sltiu $v0, $v1, 0x3
    sll $v0, $v1, 2
    lw $v0, 0x0($fp)
    jr $v0
    nop
    lw $v0, -0x6000($s5)
    sb $zero, -0x5000($s3)
    sw $v0, -0x6000($s5)
    j .Lend
    nop
    jal copyBlock
    addiu $a0, $zero, 0x1
    j .Lend
    nop
    jal loadBlock
    nop
.Lend:
    bne $s0, $zero, .Ltop
    nop
    lui $a0, (0xB0001230 >> 16)
    ori $a0, $a0, (0xB0001230 & 0xFFFF)
    jal store
    addu $a1, $zero, $zero
    lw $ra, 0x10($sp)
    lw $s3, 0x14($sp)
    lw $s5, 0x18($sp)
    jr $ra
    addiu $sp, $sp, 0x20
""")

SOURCE = """s32 poll(void);
void wait(s32);
void store(u32, u32);
void loadBlock(s32);
extern s32 D_80201234;
extern u8 D_80205678;

void serve(void)
{
    s32 command;

    do {
        command = poll();
        if (command == 0) {
            wait(16);
        }
        switch (command) {
        case 4:
            D_80205678 = 0;
            D_80201234 &= ~1;
            break;
        case 5:
            loadBlock(1);
            break;
        }
    } while (command != 0);
}
"""


def _children():
    return dict(repair.variants(SOURCE, 'serve', ASM, ''))


def test_stale_globals_take_the_targets_addresses():
    child = _children()[repair.FAMILY_GLOBAL]
    assert 'extern s32 D_800FA000;' in child
    assert 'extern u8 D_800FB000;' in child
    assert 'D_80205678' not in child and 'D_80201234' not in child


def test_a_constant_no_call_is_given_moves_the_call_and_adds_the_last_case():
    child = _children()[repair.FAMILY_CALL]
    assert 'void copyBlock(s32);' in child
    assert 'void loadBlock(void);' in child
    assert 'copyBlock(1);' in child
    assert 'case 6:\n            loadBlock();\n            break;\n        }' in child


def test_the_call_after_the_last_loop_is_added():
    child = _children()[repair.FAMILY_EXIT]
    assert '} while (command != 0);\n    store(0xB0001230, 0);\n}' in child


def test_the_whole_child_has_every_edit():
    family, child = repair.variants(SOURCE, 'serve', ASM, '')[0]
    assert family == repair.FAMILY
    for text in ('D_800FA000 &= ~1;', 'copyBlock(1);', 'case 6:', 'store(0xB0001230, 0);'):
        assert text in child


def test_nothing_for_a_source_that_already_fits():
    fitted = repair.variants(SOURCE, 'serve', ASM, '')[0][1]
    assert repair.variants(fitted, 'serve', ASM, '') == []


def test_no_assembly_no_children():
    assert repair.variants(SOURCE, 'serve', '', '') == []


def test_a_switch_arms_last_global_update_moves_to_the_front():
    source = """extern s32 D_800FA000;
extern u8 D_800FB000;
extern u8 D_800FB002;
void serve(s32 command)
{
    switch (command) {
    case 4:
        D_800FB000 = 0;
        D_800FB002 = 0;
        D_800FA000 &= ~1;
        wait(1);
        break;
    }
}
"""
    wanted = source.replace("""        D_800FB000 = 0;
        D_800FB002 = 0;
        D_800FA000 &= ~1;
""", """        D_800FA000 &= ~1;
        D_800FB000 = 0;
        D_800FB002 = 0;
""")
    assert (store_run_order.FAMILY, wanted) in store_run_order.variants(source, 'serve', '')


def test_a_volatile_global_stays_in_place():
    source = """extern volatile u8 D_800FB000;
extern u8 D_800FB002;
void serve(void)
{
    D_800FB000 = 0;
    D_800FB002 = 0;
}
"""
    assert store_run_order.variants(source, 'serve', '') == []


def test_a_global_is_not_moved_past_a_pointer_store():
    source = """extern u8 D_800FB002;
void serve(u8 *p)
{
    p[0] = 0;
    D_800FB002 = 0;
}
"""
    assert store_run_order.variants(source, 'serve', '') == []
