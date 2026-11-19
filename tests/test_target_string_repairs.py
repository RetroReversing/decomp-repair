"""A string literal written as the target's symbol."""
from decomprepair import target_string_repairs as t

SOURCE = '''void f(void) {
    g(M2C_FIELD(D_80109BB0, s32 *, 0x18) + 0x28, "%s", h(0x10));
}
'''
ASM = 'lui        $a1, %hi(D_800D2AA0)\naddiu      $a1, $a1, %lo(D_800D2AA0)\nlw $v0, %lo(D_80109BB0)($v0)\n'


def test_the_literal_becomes_the_symbol():
    (family, out), = t.variants(SOURCE, 'f', ASM)
    assert family == 'target_string_symbol'
    assert 'extern char D_800D2AA0[];\nvoid f(void)' in out and ', D_800D2AA0, h(0x10));' in out


def test_left_alone_when_the_counts_differ():
    assert t.variants(SOURCE, 'f', 'lw $v0, %lo(D_80109BB0)($v0)\n') == []
    assert t.variants(SOURCE.replace('"%s"', '0'), 'f', ASM) == []
