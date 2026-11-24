"""void_returned_local: a `void` draft whose target returns a local pointer in $v0 is declared to return it."""
from decomprepair import registry
from decomprepair import void_returned_local as vrl

# An object builder (KMC GCC 2.7.2, N64): the allocation kept in $s0, the last store addressed through a $v0 copy of it.
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))

void *alloc(s32, s32);
void setup(void *);

void f(void *arg0) {
    void *temp_v0;

    temp_v0 = alloc(M2C_FIELD(arg0, s32 *, 0x70) + 0x3C, 0);
    setup(temp_v0);
    M2C_FIELD(temp_v0, s32 *, 0) = 0x1021;
    M2C_FIELD(temp_v0, s32 *, 0x70) = (s32) M2C_FIELD(arg0, s32 *, 0x70);
}
'''
ASM = '''glabel f
/* 0 80001000 27BDFFE0 */  addiu      $sp, $sp, -0x20
/* 4 80001004 AFB10014 */  sw         $s1, 0x14($sp)
/* 8 80001008 00808821 */  addu       $s1, $a0, $zero
/* C 8000100C AFBF0018 */  sw         $ra, 0x18($sp)
/* 10 80001010 AFB00010 */  sw         $s0, 0x10($sp)
/* 14 80001014 0C000000 */  jal        alloc
/* 18 80001018 00000000 */  nop
/* 1C 8000101C 00408021 */  addu       $s0, $v0, $zero
/* 20 80001020 0C000000 */  jal        setup
/* 24 80001024 02002021 */  addu       $a0, $s0, $zero
/* 28 80001028 24021021 */  addiu      $v0, $zero, 0x1021
/* 2C 8000102C AE020000 */  sw         $v0, 0x0($s0)
/* 30 80001030 8E230070 */  lw         $v1, 0x70($s1)
/* 34 80001034 02001021 */  addu       $v0, $s0, $zero
/* 38 80001038 AC430070 */  sw         $v1, 0x70($v0)
/* 3C 8000103C 8FBF0018 */  lw         $ra, 0x18($sp)
/* 40 80001040 8FB10014 */  lw         $s1, 0x14($sp)
/* 44 80001044 8FB00010 */  lw         $s0, 0x10($sp)
/* 48 80001048 03E00008 */  jr         $ra
/* 4C 8000104C 27BD0020 */  addiu      $sp, $sp, 0x20
endlabel f
'''


def test_a_void_draft_returns_the_local_the_target_copies_into_v0():
    out = vrl.variants(SOURCE, 'f', ASM)
    assert [family for family, _ in out] == [vrl.FAMILY, vrl.FAMILY]
    pointer, word = (text for _, text in out)
    assert 'void * f(void *arg0) {' in pointer
    assert pointer.rstrip().endswith('= (s32) M2C_FIELD(arg0, s32 *, 0x70);\n    return temp_v0;\n}')
    assert 's32 f(void *arg0) {' in word and word.rstrip().endswith('return (s32) temp_v0;\n}')


def test_a_bare_return_after_the_assignment_is_rewritten():
    source = SOURCE.replace('    setup(temp_v0);', '    if (arg0 == 0) {\n        return;\n    }\n    setup(temp_v0);')
    out = vrl.variants(source, 'f', ASM)
    assert out and 'return temp_v0;\n    }' in out[0][1] and 'return;' not in out[0][1]


def test_a_bare_return_before_the_assignment_stays_an_early_exit():
    source = SOURCE.replace('    temp_v0 = alloc', '    if (arg0 == 0) {\n        return;\n    }\n    temp_v0 = alloc')
    out = vrl.variants(source, 'f', ASM)
    assert [family for family, _ in out] == [vrl.FAMILY, vrl.FAMILY]
    pointer = out[0][1]
    assert 'void * f(void *arg0) {' in pointer
    # the exit that runs before the object exists is left alone, the final return is added
    assert pointer.count('return;') == 1 and pointer.rstrip().endswith('return temp_v0;\n}')


def test_early_and_late_bare_returns_are_told_apart():
    source = SOURCE.replace('    temp_v0 = alloc', '    if (arg0 == 0) {\n        return;\n    }\n    temp_v0 = alloc')
    source = source.replace('    setup(temp_v0);', '    if (arg0 == 1) {\n        return;\n    }\n    setup(temp_v0);')
    pointer = vrl.variants(source, 'f', ASM)[0][1]
    assert pointer.count('return;') == 1 and 'return temp_v0;\n    }' in pointer


FENCED = SOURCE.replace(
    '    M2C_FIELD(temp_v0, s32 *, 0) = 0x1021;\n    M2C_FIELD(temp_v0, s32 *, 0x70) = (s32) M2C_FIELD(arg0, s32 *, 0x70);',
    '    do { M2C_FIELD(temp_v0, s32 *, 0) = 0x1021; } while (0);\n'
    '    { do { M2C_FIELD(temp_v0, s32 *, 0x70) = (s32) M2C_FIELD(arg0, s32 *, 0x70); } while (0); }')


def test_a_fenced_best_also_gets_the_return_on_its_unfenced_form():
    out = vrl.variants(FENCED, 'f', ASM)
    assert [family for family, _ in out] == [vrl.FAMILY, vrl.FAMILY, vrl.UNFENCED, vrl.UNFENCED]
    kept, opened = out[0][1], out[2][1]
    assert 'do {' in kept and 'return temp_v0;' in kept
    assert 'do {' not in opened and 'while (0)' not in opened and opened.rstrip().endswith('return temp_v0;\n}')


def test_a_function_with_no_fence_has_no_unfenced_child():
    assert vrl.UNFENCED not in [family for family, _ in vrl.variants(SOURCE, 'f', ASM)]


def test_no_child_without_the_evidence():
    assert vrl.variants(SOURCE.replace('void f', 's32 f'), 'f', ASM) == []
    assert vrl.variants(SOURCE, 'f', ASM.replace('addu       $v0, $s0, $zero', 'addiu      $v0, $zero, 1')) == []
    assert vrl.variants(SOURCE, 'f', ASM, header='void f(void *);') == []
    # an argument register is void_parameter_return's
    assert vrl.variants(SOURCE, 'f', ASM.replace('$v0, $s0, $zero', '$v0, $a0, $zero')) == []


def test_it_declares_itself():
    families = [f for r in registry.declared() for f in r.families]
    assert vrl.FAMILY in families and vrl.UNFENCED in families
