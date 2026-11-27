"""asm_cursor_commands: a scrambled cursor run rebuilt from the target's own stores."""
from decomprepair import asm_cursor_commands as acc
from decomprepair import registry

NAME = 'func_80040000'
# m2c's draft: the second command's w0 is written through the re-read cursor, one command too far
SOURCE = '''extern void *gCursor;
extern void *D_80100000;

void func_80040000(void) {
    void **__base_gCursor;
    void *temp_a2;
    void *temp_v1;

    __base_gCursor = &gCursor;
    temp_a2 = (*__base_gCursor);
    temp_v1 = (*__base_gCursor) + 8;
    (*__base_gCursor) = temp_v1;
    (*(s32 *)((char *)(temp_a2) + 0)) = 0xE7000000;
    (*(s32 *)((char *)(temp_a2) + 4)) = 0;
    (*__base_gCursor) = temp_v1 + 8;
    (*(s32 *)((char *)((*__base_gCursor)) + 8)) = 0xFB000000;
    (*(void **)((char *)(temp_v1) + 4)) = (void *) (D_80100000 + 0x48);
}
'''
ASM = '''
glabel func_80040000
    /* 0 */  lui        $a1, %hi(D_80090000)
    /* 4 */  lw         $v1, %lo(D_80090000)($a1)
    /* 8 */  lui        $v0, (0xE7000000 >> 16)
    /* c */  addu       $a2, $v1, $zero
    /* 10 */  addiu     $v1, $v1, 0x8
    /* 14 */  sw        $v1, %lo(D_80090000)($a1)
    /* 18 */  sw        $v0, 0x0($a2)
    /* 1c */  sw        $zero, 0x4($a2)
    /* 20 */  lui       $a0, %hi(D_80100000)
    /* 24 */  lw        $a0, %lo(D_80100000)($a0)
    /* 28 */  addiu     $v0, $v1, 0x8
    /* 2c */  lui       $t0, (0xFB000000 >> 16)
    /* 30 */  sw        $v0, %lo(D_80090000)($a1)
    /* 34 */  sw        $t0, 0x0($v1)
    /* 38 */  addiu     $v0, $a0, 0x48
    /* 3c */  jr        $ra
    /* 40 */   sw       $v0, 0x4($v1)
endlabel func_80040000
'''


def test_the_commands_come_from_the_targets_stores():
    assert acc.commands(ASM) == {'D_80090000': [(('const', 0xE7000000), ('const', 0)),
                                                (('const', 0xFB000000), ('load', 'D_80100000', 0x48))]}


def test_the_run_is_written_as_one_block_per_command():
    # the listing keeps the address name of the cursor the project renamed to gCursor
    (family, text), = acc.variants(SOURCE, NAME, asm=ASM)
    assert family == 'asm_cursor_commands'
    assert 'extern CursorCommand *gCursor;' in text
    assert text.count('CursorCommand *cmd = gCursor++;') == 2
    assert 'cmd->w0 = 0xFB000000;\n        cmd->w1 = (unsigned int)((char *)D_80100000 + 0x48);' in text
    assert '__base_gCursor =' not in text


def test_a_cursor_only_the_header_declares_is_cast():
    source = SOURCE.replace('extern void *gCursor;\n', '')
    (_, text), = acc.variants(source, NAME, header='extern Gfx *gCursor;\n', asm=ASM)
    assert 'CursorCommand *cmd = (*(CursorCommand **)&gCursor)++;' in text


def test_nothing_is_proposed_without_every_word_or_with_other_work_in_the_run():
    assert acc.variants(SOURCE, NAME, asm='') == []
    assert acc.variants(SOURCE, NAME, arch='ppc', asm=ASM) == []
    assert acc.variants(SOURCE, NAME, asm=ASM.replace('sw        $zero, 0x4($a2)', 'nop')) == []
    assert acc.variants(SOURCE.replace('    (*__base_gCursor) = temp_v1 + 8;\n', '    flush();\n'), NAME, asm=ASM) == []
    called = SOURCE.replace('    (*(s32 *)((char *)(temp_a2) + 4)) = 0;\n', '    flush(temp_a2);\n')
    assert acc.variants(called, NAME, asm=ASM) == []
    later = SOURCE.replace('(D_80100000 + 0x48);\n', '(D_80100000 + 0x48);\n    D_80100000 = 0;\n    sink = temp_a2;\n')
    assert acc.variants(later, NAME, asm=ASM) == []


def test_a_global_set_from_the_cursor_is_left_alone():
    kept = SOURCE.replace('(D_80100000 + 0x48);\n', '(D_80100000 + 0x48);\n    gLast = temp_a2;\n')
    assert acc.variants(kept, NAME, asm=ASM) == []


def test_the_module_declares_itself():
    assert acc.REPAIR['variants'] is acc.variants
    assert any(r.module == 'asm_cursor_commands' for r in registry.all())
