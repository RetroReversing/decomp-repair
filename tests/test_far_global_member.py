from decomprepair import far_global_member_repairs as family
from decomprepair import registry

ASM = """
  lui        $v0, %hi(D_80090000)
  addiu      $v0, $v0, %lo(D_80090000)
  lui        $v1, (0x27000 >> 16)
  addu       $v1, $v0, $v1
  lui        $a1, %hi(D_800E0000)
  lw         $a1, %lo(D_800E0000)($a1)
  sh         $a3, (0x27000 & 0xFFFF)($v1)
  sh         $a3, 0x6170($v0)
  sw         $a1, (0x27020 & 0xFFFF)($v1)
"""
SOURCE = """typedef short s16;
extern char D_80090000[];
extern s16 D_800B7000;
extern s16 D_800DE170;
extern int D_800B7020;
extern int D_800E0000;

void f(void) {
    D_800B7000 = 2;
    D_800DE170 = 2;
    D_800B7020 = D_800E0000;
}
"""


def test_writes_every_far_global_of_a_base_as_members_of_one_struct():
    [(label, text)] = family.variants(SOURCE, 'f', asm=ASM)
    assert label == 'far_global_member'
    assert ('extern struct { char pad_0[0x27000]; s16 x_27000; char pad_27002[0x1E]; int x_27020; '
            'char pad_27024[0x2714C]; s16 x_4E170; } D_80090000;') in text
    assert 'D_80090000.x_27000 = 2;' in text and 'D_80090000.x_4E170 = 2;' in text
    assert 'D_80090000.x_27020 = D_800E0000;' in text
    assert 'D_800B7000' not in text and 'D_800DE170' not in text
    assert 'extern int D_800E0000;' in text


def test_declares_the_base_the_source_does_not():
    [(_, text)] = family.variants(SOURCE.replace('extern char D_80090000[];\n', ''), 'f', asm=ASM)
    assert text.index('} D_80090000;') < text.index('void f(void)')


def test_leaves_what_the_target_names_or_never_reaches():
    assert family.variants(SOURCE, 'f', asm='') == []
    assert family.variants(SOURCE, 'f', asm=ASM.replace('addiu      $v0, $v0, %lo(D_80090000)', 'nop')) == []
    named = ASM + '  lui $t0, %hi(D_800B7000)\n  lui $t0, %hi(D_800DE170)\n  lui $t0, %hi(D_800B7020)\n'
    assert family.variants(SOURCE, 'f', asm=named) == []
    # a header that declares the base keeps its type
    assert family.variants(SOURCE, 'f', header='extern char D_80090000[];\n', asm=ASM) == []
    # the function uses the base itself
    assert family.variants(SOURCE.replace('    D_800B7000 = 2;', '    g(D_80090000);\n    D_800B7000 = 2;'), 'f',
                           asm=ASM) == []


def test_is_declared_for_the_registry():
    repair = registry.get('far_global_member_repairs')
    assert repair and registry.problems(repair) == []
