"""A mirrored sibling's transplant: which global each use reads, what is added to it and what it is compared with."""
from decomprepair.global_site_forms import FAMILY, REPAIR, variants

SOURCE = """extern s8 D_80000010;
extern u8 D_80000020;

void turn(s32 i)
{
    obj[i].x = D_80000010 * 400.0f * 0.5f;
    obj[i].z = (D_80000010 - 1) * 400.0f * 0.5f;
    if (D_80000010 != 0) {
        D_80000020 = 1;
    }
}
"""

ASM = """
    lb         $v0, %lo(D_80000010)($v0)
    addiu      $v0, $v0, -0x1
    mtc1       $v0, $f0
    lb         $v0, %lo(D_80000030)($v0)
    nop
    mtc1       $v0, $f0
    lb         $v0, %lo(D_80000010)($v0)
    slti       $v0, $v0, 0x17
    beqz       $v0, .L80000100
"""


def test_the_sibling_is_one_child():
    children = [child for _, child in variants(SOURCE, 'turn', asm=ASM)]
    wanted = [c for c in children if 'x = (D_80000010 - 1) *' in c and 'z = D_80000030 *' in c
              and 'D_80000010 < 23' in c]
    assert wanted
    assert 'extern s8 D_80000030;' in wanted[0]
    assert all(family == FAMILY for family, _ in variants(SOURCE, 'turn', asm=ASM))


def test_single_changes_come_first():
    first = variants(SOURCE, 'turn', asm=ASM)[0][1]
    assert sum(a != b for a, b in zip(SOURCE.splitlines(), first.splitlines())) <= 2


def test_inverted_test_keeps_its_polarity():
    source = SOURCE.replace('D_80000010 != 0', 'D_80000010 == 0')
    assert any('D_80000010 >= 23' in child for _, child in variants(source, 'turn', asm=ASM))


def test_nothing_without_facts():
    assert variants(SOURCE, 'turn', asm='lw $v0, 0($a0)') == []
    assert variants(SOURCE, 'other', asm=ASM) == []


def test_declares_itself():
    assert REPAIR['needs'] == ('source', 'name', 'asm')
