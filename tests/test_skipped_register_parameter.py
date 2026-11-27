"""A parameter m2c left out because nothing reads it, put back and passed on to the first callee."""
from decomprepair import registry
from decomprepair.skipped_register_parameter import FAMILY, variants

# a loader that hands its first argument on to a header parser, as m2c drafts it
DRAFT = '''s32 func_80001000();                            /* extern */

s32 load(void *arg1, s32 *arg2) {
    func_80001000();
    *arg2 = M2C_FIELD(arg1, s32 *, 0);
    return 0;
}
'''

ASM = '''glabel load
/* 000 80000000 27BDFFE0 */  addiu      $sp, $sp, -0x20
/* 004 80000004 AFB00010 */  sw         $s0, 0x10($sp)
/* 008 80000008 00A08021 */  addu       $s0, $a1, $zero
/* 00C 8000000C AFB10014 */  sw         $s1, 0x14($sp)
/* 010 80000010 00C08821 */  addu       $s1, $a2, $zero
/* 014 80000014 0C000400 */  jal        func_80001000
/* 018 80000018 AFBF0018 */  sw         $ra, 0x18($sp)
/* 01C 8000001C 8E020000 */  lw         $v0, 0x0($s0)
/* 020 80000020 03E00008 */  jr         $ra
/* 024 80000024 27BD0020 */  addiu      $sp, $sp, 0x20
endlabel load
'''


def texts(source=DRAFT, **kw):
    return [text for _, text in variants(source, 'load', **kw)]


def test_the_parameter_alone_without_assembly():
    (child,) = texts()
    assert 's32 load(s32 arg0, void *arg1, s32 *arg2)' in child
    assert 'func_80001000();\n    *arg2' in child


def test_each_argument_count_is_offered_to_the_first_callee():
    children = texts(asm=ASM, arch='mips')
    assert all(family == FAMILY for family, _ in variants(DRAFT, 'load', asm=ASM, arch='mips'))
    assert 'func_80001000(arg0);' in children[1]
    assert 'func_80001000(arg0, arg1);' in children[2]
    assert 'func_80001000(arg0, arg1, arg2);' in children[3]
    assert len(children) == 4  # $a3 is untouched but no parameter names it


def test_a_prototyped_callee_keeps_its_arguments():
    assert len(texts(asm=ASM, header='void func_80001000(void);')) == 1


def test_no_gap_no_child():
    assert not texts(DRAFT.replace('void *arg1, s32 *arg2', 'void *arg0, s32 *arg1'))
    assert not texts(DRAFT.replace('void *arg1, s32 *arg2', 'f32 arg1'))
    assert not texts(DRAFT.replace('void *arg1', 'void *object'))


def test_registry_declares_it():
    assert any(repair.module == 'skipped_register_parameter' for repair in registry.declared())
