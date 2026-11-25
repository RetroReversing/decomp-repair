"""struct_field_copy_fold (rules/struct_field_copy_fold.json): `d = A[i].f;` written `d = *&A[i].f;`.

A save-menu function of an N64 game (SN GCC 2.8.1) copied a 0x20-byte record field out of a global array twice:
`D_800BD0B8 = D_8014ABC0[k].sub54;` compiled the copy as `lw t1, 0x54(v0)` ... with v0 = &D_8014ABC0[k], while the
target loads `lw t1, 0(v0)` with v0 = (&D_8014ABC0 + 0x54) + k * 0xB4. `*&D_8014ABC0[k].sub54` makes GCC fold the
field offset into the symbol (plus_constant on the address), which closed 4110 -> 685 for both copies."""
import json

from decomprepair import registry, rules

ASM = '''glabel f
/* 0 80001000 8C490000 */  lw         $t1, 0x0($v0)
/* 4 80001004 03E00008 */  jr         $ra
endlabel f
'''
SOURCE = '''void f(s32 k) {
    D_800BD0B8 = D_8014ABC0[D_800B81C8].sub54;
    x = 1;
    D_800BD0B8 = D_8014ABC0[k + 1].sub54;
}
'''


def test_the_rule_is_valid_and_declared():
    path = rules.PACKAGED / 'struct_field_copy_fold.json'
    assert rules.problems(json.loads(path.read_text(encoding='utf-8'))) == []
    repair = registry.get('rule:struct_field_copy_fold')
    assert repair is not None and registry.problems(repair) == []
    assert repair.families == ('struct_field_copy_fold', 'struct_field_copy_fold_one')
    assert repair.runs_in('local', 'mips') and not repair.runs_in('local', 'ppc')


def test_every_copy_and_each_copy_alone():
    out = registry.run('rule:struct_field_copy_fold', source=SOURCE, name='f', asm=ASM, header='', arch='mips')
    assert [family for family, _ in out] == ['struct_field_copy_fold', 'struct_field_copy_fold_one',
                                            'struct_field_copy_fold_one']
    both = out[0][1]
    assert 'D_800BD0B8 = *&D_8014ABC0[D_800B81C8].sub54;' in both
    assert 'D_800BD0B8 = *&D_8014ABC0[k + 1].sub54;' in both
    assert out[1][1].count('*&') == 1 and out[2][1].count('*&') == 1


def test_leaves_comparisons_calls_and_already_folded_copies_alone():
    source = '''void f(s32 k) {
    if (a == B[k].c) {
        g(B[k].c);
    }
    d = *&B[k].c;
    e = B[k].c.d;
}
'''
    assert registry.run('rule:struct_field_copy_fold', source=source, name='f', asm=ASM, header='', arch='mips') == []


def test_needs_a_word_load_in_the_target():
    assert registry.run('rule:struct_field_copy_fold', source=SOURCE, name='f', asm=ASM.replace('lw ', 'lb '),
                        header='', arch='mips') == []
