"""Literals the target computes from one saved register, written as sums off a variable again."""
from decomprepair import register_constant_base as m

ASM = """
glabel panel
    /* 000000 80000000 00000000 */  addiu      $sp, $sp, -0x30
    /* 000004 80000004 00000000 */  sw         $s6, 0x20($sp)
    /* 000008 80000008 00000000 */  addiu      $s6, $zero, 0x40
    /* 00000C 8000000C 00000000 */  beqz       $v0, .L80000024
    /* 000010 80000010 00000000 */  addiu      $s6, $zero, -0x30
    /* 000014 80000014 00000000 */  addiu      $a1, $s6, 0x18
    /* 000018 80000018 00000000 */  addu       $a1, $s6, $zero
  .L80000024:
    /* 000024 80000024 00000000 */  addiu      $a1, $s6, 0x20
    /* 000028 80000028 00000000 */  lw         $s6, 0x20($sp)
    /* 00002C 8000002C 00000000 */  jr         $ra
"""

SOURCE = """void panel(void) {
    s32 i;

    i = 0;
    if (mode != 0) {
        setup(0);
        do {
            draw(i, -0x30);
            draw(i, -0x18);
            pos.x = (f32) -0x30;
            i++;
        } while (i < 4);
        return;
    }
    draw(i, 0x40);
    draw(i, 0x60);
}
"""


def test_register_constants_come_from_the_saved_registers_only():
    assert m.register_constants(ASM) == [('$s6', [0x40, -0x30], {0x18, 0x20})]
    assert m.register_constants(ASM + '\n    addu $s6, $v0, $zero\n') == []


def test_one_variable_for_the_register():
    children = m.variants(SOURCE, 'panel', ASM)
    texts = [text for family, text in children if family == m.FAMILY]
    child = texts[0]
    assert 's32 reg_base;' in child
    assert 'reg_base = 0x40;' in child and 'reg_base = -0x30;' in child
    assert child.index('reg_base = 0x40;') < child.index('reg_base = -0x30;') < child.index('do {')
    assert 'draw(i, reg_base);' in child
    assert 'draw(i, (reg_base + 0x18));' in child
    assert 'draw(i, (reg_base + 0x20));' in child
    assert 'pos.x = (f32) reg_base;' in child
    assert 'i < 4' in child and 'setup(0)' in child
    # the later constant can also go ahead of the arm's first statement
    assert any(text.index('reg_base = -0x30;') < text.index('setup(0)') for text in texts)
    assert any(family == m.PER_VALUE for family, _ in children)


def test_no_child_when_a_later_assignment_would_reach_the_first_value():
    source = SOURCE.replace('        return;\n', '')
    assert not [text for family, text in m.variants(source, 'panel', ASM) if family == m.FAMILY]


def test_no_child_without_the_register_evidence():
    assert m.variants(SOURCE, 'panel', '    addiu $a1, $zero, 0x40\n') == []
    assert m.variants(SOURCE, 'panel') == []
