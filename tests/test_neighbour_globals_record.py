"""Globals the target reaches from one another's address, as one record (an N64 clamp routine)."""
from decomprepair.neighbour_globals_record import FAMILY, variants

SOURCE = '''extern u8 D_801C5EA0;
extern s16 D_8021E1A2;
extern s8 D_8021E190;
extern s8 D_8021E18F;
extern s16 D_8021E18C;

void clamp(void) {
    if (D_8021E1A2 < 2) {
        D_8021E190 = 0;
        D_8021E18F = 8;
    }
    if (D_8021E18C > D_8021E18F) {
        D_8021E18C = D_8021E190;
    }
    D_801C5EA0 = 0;
}
'''
ASM = '''lui        $s0, %hi(D_8021E1A2)
addiu      $s0, $s0, %lo(D_8021E1A2)
lh         $v0, 0x0($s0)
sb         $zero, -0x12($s0)
sb         $v0, -0x13($s0)
lui        $a0, %hi(D_8021E18C)
addiu      $a0, $a0, %lo(D_8021E18C)
lh         $v1, 0x0($a0)
lb         $v0, 0x3($a0)
'''


def test_the_linked_globals_become_one_record_at_the_lowest():
    (found,) = variants(SOURCE, 'clamp', '', ASM)
    family, out = found
    assert family == FAMILY
    assert ('typedef struct {\n    s16 unk0;\n    u8 pad2[0x1];\n    s8 unk3;\n    s8 unk4;\n    u8 pad5[0x11];\n'
            '    s16 unk16;\n} Record_D_8021E18C;\nextern Record_D_8021E18C D_8021E18C;\n') in out
    assert 'extern s8 D_8021E190;' not in out and 'extern u8 D_801C5EA0;' in out
    assert 'if (D_8021E18C.unk16 < 2) {\n        D_8021E18C.unk4 = 0;\n        D_8021E18C.unk3 = 8;' in out
    assert 'if (D_8021E18C.unk0 > D_8021E18C.unk3) {\n        D_8021E18C.unk0 = D_8021E18C.unk4;' in out


def test_nothing_without_the_evidence_or_with_a_header_declaration_or_an_overlap():
    assert variants(SOURCE, 'clamp', '', '') == []
    assert variants(SOURCE, 'clamp', '', 'lh $v0, 0x0($s0)\n') == []
    only = 'addiu $s0, $s0, %lo(D_8021E1A2)\nsb $zero, -0x12($s0)\n'
    assert variants(SOURCE, 'clamp', 'extern s8 D_8021E190;', only) == []
    assert variants(SOURCE.replace('extern s8 D_8021E18F;', 'extern s32 D_8021E18F;'), 'clamp', '', ASM) == []


def test_a_register_written_again_links_nothing():
    asm = 'addiu $s0, $s0, %lo(D_8021E1A2)\nlw $s0, 0x0($v1)\nsb $zero, -0x12($s0)\n'
    assert variants(SOURCE, 'clamp', '', asm) == []
