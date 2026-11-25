"""abs_idiom: a hand-written conditional negation is the C library's abs() (bltzl with the negu in its slot)."""
from decomprepair import abs_idiom as ab
from decomprepair import registry

SOURCE = '''void f(void *arg0) {
    s32 var_v0;
    s32 var_v0_2;
    s32 temp_ft1;

    var_v0 = (s32) (M2C_FIELD(arg0, f32 *, 4) - M2C_FIELD(arg0, f32 *, 8));
    if (var_v0 < 0) {
        var_v0 = -var_v0;
    }
    temp_ft1 = (s32) M2C_FIELD(arg0, f32 *, 0xC);
    if (var_v0 < 0xC9) {
        var_v0_2 = temp_ft1;
        if (temp_ft1 < 0) {
            var_v0_2 = -var_v0_2;
        }
        if (var_v0_2 < 0xC9) {
            M2C_FIELD(arg0, s32 *, 0x9C) = 1;
        }
    }
}
'''
ASM = '''glabel f
/* 0 80001000 04420001 */  bltzl      $v0, .L80001008
/* 4 80001004 00021023 */  negu       $v0, $v0
.L80001008:
/* 8 80001008 03E00008 */  jr         $ra
/* C 8000100C 00000000 */  nop
endlabel f
'''


def test_every_site_and_each_site_alone_are_children_and_abs_is_declared():
    out = ab.variants(SOURCE, 'f', ASM)
    assert [family for family, _ in out] == [ab.FAMILY, ab.FAMILY + '_one', ab.FAMILY + '_one']
    everything = out[0][1]
    assert everything.startswith('int abs(int);\nvoid f(')
    assert 'var_v0 = abs((s32) (M2C_FIELD(arg0, f32 *, 4) - M2C_FIELD(arg0, f32 *, 8)));' in everything
    assert 'var_v0_2 = abs(temp_ft1);' in everything and '= -var' not in everything
    assert '= -var' in out[1][1] and 'abs(temp_ft1)' not in out[1][1] and 'abs((s32)' in out[1][1]
    assert 'abs(temp_ft1)' in out[2][1] and 'abs((s32)' not in out[2][1]


def test_a_bare_test_is_abs_of_the_variable_and_a_declared_abs_is_not_redeclared():
    bare = 'void f(s32 a) {\n    if (a < 0) {\n        a = -a;\n    }\n    g(a);\n}\n'
    out = ab.variants(bare, 'f', ASM, 'int abs(int);\n')
    assert out == [(ab.FAMILY, 'void f(s32 a) {\n    a = abs(a);\n    g(a);\n}\n')]


def test_no_child_without_a_negate_a_float_or_another_test():
    assert ab.variants(SOURCE, 'f', ASM.replace('negu', 'addu')) == []
    assert ab.variants(SOURCE.replace('s32 var_v0;', 'f32 var_v0;'), 'f', ASM)[0][1].count('= abs(') == 1
    assert ab.variants('void f(s32 a) {\n    if (a < 1) {\n        a = -a;\n    }\n}\n', 'f', ASM) == []
    assert ab.variants('void f(s32 a) {\n    if (a < 0) {\n        a = -a;\n    } else {\n        g();\n    }\n}\n', 'f', ASM) == []


def test_subu_from_zero_counts_as_a_negate_and_it_is_registered():
    assert ab.negates('/* 0 80001000 00021023 */  subu       $v0, $zero, $v0\n')
    assert not ab.negates('/* 0 80001000 00021023 */  subu       $v0, $v1, $v0\n')
    assert [r.module for r in registry.declared() if r.module in ('abs_idiom', 'rule:abs_idiom')] == ['rule:abs_idiom']
