from decomprepair.far_record_members import FAMILY, accesses, variants

ASM = """
glabel setup
lui        $v0, %hi(D_80100000)
addiu      $v0, $v0, %lo(D_80100000)
lui        $a0, (0x27168 >> 16)
addu       $a0, $v0, $a0
lui        $t1, (0x48000 >> 16)
ori        $t1, $t1, (0x48000 & 0xFFFF)
addu       $v0, $v0, $t1
addiu      $t0, $zero, 0x2
sh         $t0, (0x27148 & 0xFFFF)($a0)
sw         $a3, (0x27168 & 0xFFFF)($a0)
jr         $ra
sh         $t0, 0x62B8($v0)
endlabel setup
"""

SOURCE = """extern char D_80100000[];
extern short D_80127148;
extern int D_80127168;
extern short D_8014E2B8;
extern int D_80200000;
void setup(void)
{
  D_80127148 = 2;
  D_8014E2B8 = 2;
  D_80127168 = D_80200000;
}
"""


def test_the_offsets_are_read_through_the_built_constants():
    assert accesses(ASM) == {'D_80100000': {0x27148: 2, 0x27168: 4, 0x4E2B8: 2}}


def test_the_split_globals_become_members_of_one_record_at_the_base():
    [(family, out)] = variants(SOURCE, 'setup', ASM)
    assert family == FAMILY
    assert 'extern Far_D_80100000 D_80100000;' in out
    assert 'unsigned char pad0[0x27148];' in out and 'short f27148;' in out and 'short f4E2B8;' in out
    assert 'D_80100000.f27148 = 2;' in out and 'D_80100000.f4E2B8 = 2;' in out
    assert 'D_80100000.f27168 = D_80200000;' in out
    assert 'extern short D_80127148;' not in out and 'extern char D_80100000[];' not in out


def test_nothing_without_evidence_or_when_the_code_names_the_base():
    assert not variants(SOURCE, 'setup', '')
    assert not variants(SOURCE.replace('D_80127148 = 2;', 'D_80100000[0] = 2;'), 'setup', ASM)
    # a width the declaration does not have is not that member
    assert not variants(SOURCE.replace('extern short D_8014E2B8;', 'extern int D_8014E2B8;')
                        .replace('extern short D_80127148;', 'extern int D_80127148;')
                        .replace('extern int D_80127168;', 'extern char D_80127168;'), 'setup', ASM)
