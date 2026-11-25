from decomprepair import registry
from decomprepair.constant_in_local import FAMILY_BOUND, FAMILY_MULTIPLIER, REPAIR, variants

SOURCE = """void step(f32 *out, f32 x, s32 n) {
    s32 i;
    f32 g;
    g = x * 7000.0f;
    *out = g;
    i = 0;
    while (i < 5) {
        *out += 1.0f;
        i += 1;
    }
}
"""
ASM = "slt $v0, $a1, $t0\nmul.s $f0, $f12, $f2\n"


def kids(source=SOURCE, family=None, asm=''):
    return [c for f, c in variants(source, 'step', asm=asm) if family in (None, f)]


def test_the_multiplier_is_held_in_a_local_set_on_the_line_before():
    child = kids(family=FAMILY_MULTIPLIER)[0]
    assert 'k_7000p0 = 7000.0f;\n    g = x * k_7000p0;' in child
    assert 'f32 k_7000p0;' in child


def test_the_loop_bound_is_held_in_a_local_above_the_loop():
    child = kids(family=FAMILY_BOUND)[0]
    assert 'n_5 = 5;\n    while (i < n_5)' in child
    assert 's32 n_5;' in child


def test_the_assembly_gate_asks_for_a_register_compare_and_a_multiply():
    assert kids(family=FAMILY_BOUND, asm=ASM) and kids(family=FAMILY_MULTIPLIER, asm=ASM)
    assert not kids(family=FAMILY_BOUND, asm='slti $v0, $a1, 5\n')
    assert not kids(family=FAMILY_MULTIPLIER, asm='addu $v0, $a1, $a2\n')


def test_a_power_of_two_or_a_statement_under_an_unbraced_if_is_left_alone():
    assert not kids(SOURCE.replace('7000.0f', '8'), FAMILY_MULTIPLIER)
    assert not kids(SOURCE.replace('    g = x * 7000.0f;', '    if (n)\n        g = x * 7000.0f;'), FAMILY_MULTIPLIER)


def test_a_do_while_gets_its_bound_above_the_do():
    source = SOURCE.replace('while (i < 5) {', 'do {').replace('        i += 1;\n    }', '        i += 1;\n    } while (i < 5);')
    child = kids(source, FAMILY_BOUND)[0]
    assert child.index('n_5 = 5;') < child.index('do {') and 'while (i < n_5);' in child


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert set(REPAIR['families']) <= {family for entry in registry.declared() for family in entry.families}


def test_one_local_set_above_two_statements_that_multiply_by_it():
    source = "void st(Obj *o) {\n    o->a = (f(1) * 400) >> 15;\n    o->b = (g(1) * 400) >> 15;\n}\n"
    children = [c for f, c in variants(source, 'st') if f == FAMILY_MULTIPLIER]
    assert children[0].count('* k_400') == 2 and children[0].count('k_400 = 400;') == 1
    assert children[1].count('* k_400') == 1  # and the one-statement form follows


def test_a_compound_assignment_holds_its_constant_too():
    source = "void st(Obj *o) {\n    o->a += (f(1) * 0x1B4) >> 15;\n}\n"
    child = [c for f, c in variants(source, 'st') if f == FAMILY_MULTIPLIER][0]
    assert 'k_0x1B4 = 0x1B4;\n    o->a += (f(1) * k_0x1B4)' in child


ARGUMENT = """void aim(Obj *o, Obj *t, s32 done) {
    f32 tgt;

    if (done == 0) {
        if (o->speed > 7.0f) {
            o->z = turn(180.0f, o->z, 29.0f);
        }
    }
}
"""


def test_a_float_argument_is_held_in_a_local_on_the_line_before_and_before_the_if_that_holds_it():
    from decomprepair.constant_in_local import FAMILY_ARGUMENT
    out = [c for f, c in variants(ARGUMENT, 'aim') if f == FAMILY_ARGUMENT and 'k_180p0 =' in c]
    assert any('k_180p0 = 180.0f;\n            o->z = turn(k_180p0, o->z, 29.0f);' in c for c in out)
    assert any('k_180p0 = 180.0f;\n        if (o->speed > 7.0f) {' in c and 'turn(k_180p0' in c for c in out)
    assert all('f32 k_180p0;' in c for c in out)
    assert not [c for f, c in variants(ARGUMENT.replace('180.0f', '1.0f'), 'aim') if f == FAMILY_ARGUMENT and 'k_1p0' in c]
