"""m2c's divide with an addend and sign-test correction (signed_division), and a chosen value as a `?:` argument."""
from decomprepair import signed_division_repairs as d
from decomprepair import ternary_argument_repairs as t

DIVIDE = '''void f(s32 arg2) {
    s32 temp_v0;
    s32 var_v0;
    s32 var_v0_2;

    var_v0 = arg2 + 0xFF;
    D_A = 1;
    if (var_v0 < 0) {
        var_v0 = arg2 + 0x1FE;
    }
    temp_v0 = var_v0 >> 8;
    var_v0_2 = temp_v0 << 8;
    D_B = var_v0_2;
    if (temp_v0 & 0x800000) {
        var_v0_2 += 0xFF;
    }
    D_C = var_v0_2 >> 8;
}
'''


def test_the_divide_with_an_addend_and_the_sign_test():
    # An N64 function at 90.6%: exact as the two divisions.
    out = [text for _, text in d.variants(DIVIDE, 'f')][-1]
    assert '    D_A = 1;\n    temp_v0 = (arg2 + 0xFF) / 0x100;\n' in out
    assert 'D_C = var_v0_2 / 0x100;' in out
    assert 'if (' not in out and 'var_v0 =' not in out


def test_left_alone_when_the_constants_disagree():
    assert d.variants(DIVIDE.replace('0x1FE', '0x1FF').replace('+= 0xFF', '+= 0xFE'), 'f') == []


CHOICE = '''void f(s32 i, s32 a) {
    void *var_a2;

    if (2U > i) {
        var_a2 = D_160[i];
    } else {
        var_a2 = (i * 0xC) + D_280;
    }
    g(a, var_a2, i);
}
'''


def test_the_choice_written_as_the_argument():
    # An N64 function at 98.7%: 99.6% with this alone.
    (family, out), = t.variants(CHOICE, 'f')
    assert family == 'ternary_argument'
    assert 'g(a, (2U > i) ? (void *) (D_160[i]) : (void *) ((i * 0xC) + D_280), i);' in out
    assert 'var_a2' not in out


def test_left_alone_when_the_value_is_used_again():
    assert t.variants(CHOICE.replace('g(a, var_a2, i);', 'g(a, var_a2, i);\n    h(var_a2);'), 'f') == []


TREE = '''void f(s32 arg1, void *p) {
    s32 t;
    s32 r;
    s32 g;
    s32 b;

    t = arg1 & 0xFF;
    if (t != 0) {
        r = 0x40;
        if (t != 1) {
            r = 0xFF;
            g = 0xFF;
        } else {
            g = 0x40;
        }
        b = 0xFF;
    } else {
        r = 0xFF;
        g = 0x40;
        b = 0x40;
    }
    h(r, g, b);
}
'''


def test_the_assignment_tree_as_a_switch():
    # An N64 function at 94.8%: exact as the switch (83.9% as if/else if).
    from decomprepair import assignment_tree_switch_repairs as a
    (family, ascending), (_, reverse) = a.variants(TREE, 'f')
    assert family == 'assignment_tree_switch'
    assert '''    switch (t) {
    case 0:
        r = 0xFF;
        g = 0x40;
        b = 0x40;
        break;
    case 1:
        r = 0x40;
        g = 0x40;
        b = 0xFF;
        break;
    default:
        r = 0xFF;
        g = 0xFF;
        b = 0xFF;
        break;
    }
    h(r, g, b);''' in ascending
    assert reverse.index('case 1:') < reverse.index('case 0:')


def test_left_alone_when_a_block_does_more_than_assign_constants():
    from decomprepair import assignment_tree_switch_repairs as a
    assert a.variants(TREE.replace('            g = 0x40;\n', '            g = k();\n'), 'f') == []
    assert a.variants(TREE.replace('if (t != 1)', 'if (u != 1)'), 'f') == []


SHARED = '''void f(void *arg0, s32 k) {
    s16 var_v0;

    switch (k) {
    case 0:
        if (g(0x3C) == 0) {
            h(arg0);
            var_v0 = 1;
block_30:
            M2C_FIELD(arg0, s16 *, 0x7A) = var_v0;
        }
        return;
    case 3:
        h(arg0);
        var_v0 = 2;
        goto block_30;
    }
}
'''


def test_the_store_at_each_of_its_sites():
    # An N64 function at 96.6%: exact with the store written in each case (gcc merged the identical tails itself).
    from decomprepair import shared_constant_store_repairs as s
    (family, returned), (_, broken) = s.variants(SHARED, 'f')
    assert family == 'shared_constant_store'
    assert '            M2C_FIELD(arg0, s16 *, 0x7A) = 1;\n        }\n        return;' in returned
    assert '        M2C_FIELD(arg0, s16 *, 0x7A) = 2;\n        return;\n' in returned
    assert 'goto' not in returned and 'var_v0' not in returned and 'block_30' not in returned
    assert '= 2;\n        break;\n' in broken


def test_left_alone_when_the_variable_is_used_again():
    from decomprepair import shared_constant_store_repairs as s
    assert s.variants(SHARED.replace('        h(arg0);\n        var_v0 = 2;', '        h(var_v0);\n        var_v0 = 2;'), 'f') == []


CARRIER = '''f32 g(f32, void *);                     /* extern */

void f(void *arg0, f32 arg1) {
    f32 temp_ft3;
    void *temp_s0;
    void *var_a0;

    var_a0 = arg0;
    temp_s0 = var_a0;
    if (temp_s0 != NULL) {
        if ((D_A == 0) || (var_a0 = (void *)1, (D_B == 1))) {
            h(temp_s0);
        }
        temp_ft3 = 1.0f / g(arg1 * 0.5f, var_a0);
        k(temp_ft3);
    }
}
'''


def test_the_carried_register_value_is_dropped():
    # An N64 function at 97.6%: exact without m2c's var_a0 and the extra argument it carried.
    from decomprepair import register_carrier_repairs as r
    (family, out), = r.variants(CARRIER, 'f')
    assert family == 'register_carrier_argument'
    assert 'f32 g(f32);' in out and 'g(arg1 * 0.5f)' in out
    assert '    temp_s0 = arg0;\n' in out and '((D_A == 0) || ((D_B == 1)))' in out
    assert 'var_a0' not in out


def test_left_alone_when_the_value_is_really_used():
    from decomprepair import register_carrier_repairs as r
    assert r.variants(CARRIER.replace('            h(temp_s0);', '            h(var_a0);'), 'f') == []
