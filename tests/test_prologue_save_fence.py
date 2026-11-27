from decomprepair import prologue_save_fence

SOURCE = '''s32 insert(void)
{
    s8 slot[2];
    u16 n;
    slot[0] = -1;
    slot[1] = -1;
    for (n = 0; n < 2; n++) {
        place(n, slot);
    }
    return slot[0];
}
'''
TOGETHER = '''glabel insert
/* 0 80000000 27BDFFD8 */  addiu      $sp, $sp, -0x28
/* 4 80000004 AFBF0020 */  sw         $ra, 0x20($sp)
/* 8 80000008 AFB1001C */  sw         $s1, 0x1C($sp)
/* C 8000000C AFB00018 */  sw         $s0, 0x18($sp)
/* 10 80000010 00008821 */  addu       $s1, $zero, $zero
'''
AMONG = '''addiu $sp, $sp, -0x28
sw $s1, 0x1c($sp)
move $s1, $zero
sw $ra, 0x20($sp)
sw $s0, 0x18($sp)
'''


def test_the_empty_loop_goes_after_the_declarations():
    (family, child), = prologue_save_fence.variants(SOURCE, 'insert', TOGETHER)
    assert family == 'prologue_save_fence'
    assert child == SOURCE.replace('    u16 n;\n', '    u16 n;\n    do { } while (0);\n')
    assert prologue_save_fence.variants(child, 'insert', TOGETHER) == []


def test_only_a_prologue_whose_saves_stay_together():
    assert prologue_save_fence.variants(SOURCE, 'insert', AMONG) == []
    assert prologue_save_fence.variants(SOURCE, 'insert', '') == []


def test_a_function_without_declarations():
    source = 'void f(void)\n{\n    g();\n}\n'
    (_, child), = prologue_save_fence.variants(source, 'f', TOGETHER)
    assert child == 'void f(void)\n{\n    do { } while (0);\n    g();\n}\n'
