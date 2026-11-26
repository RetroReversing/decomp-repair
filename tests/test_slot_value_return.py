from decomprepair.slot_value_return import FAMILY, slot_writes, variants

ASM = """
glabel check
    addu       $s1, $zero, $zero
    addu       $v0, $s2, $s1
.L1:
    lb         $v1, 0x60($v0)
    addiu      $s1, $s1, 0x1
    slti       $v0, $s1, 0x7
    bnez       $v0, .L1
     addu      $v0, $s2, $s1
    lw         $ra, 0x24($sp)
    jr         $ra
     addiu     $sp, $sp, 0x58
"""

SOURCE = """s32 check(s32 arg0, u8 *arg1) {
    s32 i;

    for (i = 0; i < 7; i++) {
        arg1[i] = 0;
    }
}
"""


def test_returns_the_value_the_slot_computes():
    assert slot_writes(ASM) == ('addu', '$v0, $s2, $s1')
    texts = [text for family, text in variants(SOURCE, 'check', ASM) if family == FAMILY]
    assert any('return (s32) ((u8 *) arg1 + i);\n}' in text for text in texts)
    assert any('return (s32) i;\n}' in text for text in texts)


def test_nothing_for_void_a_returning_source_or_a_likely_branch():
    assert variants(SOURCE.replace('s32 check', 'void check'), 'check', ASM) == []
    assert variants(SOURCE.replace('    }\n}', '    }\n    return 0;\n}'), 'check', ASM) == []
    assert variants(SOURCE, 'check', ASM.replace('bnez ', 'bnezl')) == []
