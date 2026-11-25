"""nonvoid_no_return: an unfilled delay slot that `$v0` would fill means `$v0` is live at the exit: declare the function s32."""
from decomprepair import nonvoid_no_return as nv
from decomprepair import registry

SOURCE = '''void g(void *arg0);
void f(void *arg0) {
    if (g(arg0) != 0) {
        M2C_FIELD(arg0, s32 *, 0x7C) = 0;
        M2C_FIELD(arg0, M2C_UNK **, 0xD8) = &h;
    }
}
'''
ASM = '''glabel f
/* 0 80001000 0C00B573 */  jal        g
/* 4 80001004 02002021 */  addu       $a0, $s0, $zero
/* 8 80001008 10400005 */  beqz       $v0, .L80001020
/* C 8000100C 00000000 */  nop
/* 10 80001010 3C028006 */  lui        $v0, %hi(h)
/* 14 80001014 24427474 */  addiu      $v0, $v0, %lo(h)
/* 18 80001018 AE00007C */  sw         $zero, 0x7C($s0)
/* 1C 8000101C AE0200D8 */  sw         $v0, 0xD8($s0)
.L80001020:
/* 20 80001020 8FBF0014 */  lw         $ra, 0x14($sp)
/* 24 80001024 03E00008 */  jr         $ra
/* 28 80001028 27BD0018 */  addiu      $sp, $sp, 0x18
endlabel f
'''


def test_the_unfilled_slot_is_the_evidence_and_the_function_becomes_s32():
    assert nv.live_at_exit(ASM)
    out = nv.variants(SOURCE.replace('void g(void *arg0);\n', 's32 g(void *arg0);\n'), 'f', ASM)
    assert [fam for fam, _ in out] == [nv.FAMILY] and 's32 f(void *arg0) {' in out[0][1] and 'return' not in out[0][1]


def test_a_filled_slot_or_a_v0_write_on_the_taken_path_is_no_evidence():
    filled = ASM.replace('beqz       $v0, .L80001020\n/* C 8000100C 00000000 */  nop', 'beqz       $v0, .L80001020\n/* C 8000100C 3C028006 */  lui        $v0, %hi(h)')
    assert not nv.live_at_exit(filled)
    assert not nv.live_at_exit(ASM.replace('.L80001020:\n', '.L80001020:\n/* 20 */  addiu      $v0, $zero, 1\n'))
    assert not nv.live_at_exit(ASM.replace('lui        $v0, %hi(h)', 'lui        $v1, %hi(h)'))


def test_prototypes_follow_and_a_value_function_or_a_void_header_gets_nothing():
    with_proto = 'void f(void *arg0);\n' + SOURCE
    assert nv.variants(with_proto, 'f', ASM)[0][1].startswith('s32 f(void *arg0);\n')
    assert nv.variants(SOURCE.replace('void f', 's32 f'), 'f', ASM) == []
    assert nv.variants(SOURCE, 'f', ASM, 'void f(void *);\n') == []
    assert nv.variants(SOURCE.replace('    }\n}', '    }\n    return 1;\n}'), 'f', ASM) == []


def test_it_is_registered():
    assert any(r.module == 'nonvoid_no_return' for r in registry.declared())
