from decomprepair import registry
from decomprepair.statement_fence import FAMILY_DEEP, FAMILY_RUN, LIMIT, REPAIR, variants

SOURCE = """void f(Obj *o) {
    s32 mask;
    s32 cm;
    s32 n;
    s32 t;

    mask = 0;
    cm = 2;
    n = 0;
    while (n < 4) {
        t = D_g * 2;
        use(t);
        use2(t);
        n += 1;
    }
}
"""


def kids(source=SOURCE, family=None):
    return [c for f, c in variants(source, 'f') if family in (None, f)]


def test_a_run_of_initialisers_is_fenced_together():
    out = kids(family=FAMILY_RUN)
    assert out and 'do { mask = 0; cm = 2; n = 0; } while (0);' in out[0]


def test_an_arithmetic_statement_is_fenced_four_and_two_deep():
    out = kids(family=FAMILY_DEEP)
    assert any('do { do { do { do { t = D_g * 2; } while (0); } while (0); } while (0); } while (0);' in c for c in out)
    assert any('do { do { t = D_g * 2; } while (0); } while (0);' in c for c in out)


def test_a_statement_already_in_a_fence_is_not_fenced_again():
    source = SOURCE.replace('t = D_g * 2;', 'do { t = D_g * 2; } while (0);')
    assert not [c for c in kids(source, FAMILY_DEEP) if 'do { do { do { do { do {' in c]


def test_a_do_while_loop_body_is_not_a_fence():
    source = 'void f(void) {\n    s32 t;\n\n    do {\n        t = D_g * 2;\n        use(t);\n        use2(t);\n    } while (t < 3);\n}\n'
    assert any('do { do { t = D_g * 2; } while (0); } while (0);' in c for c in kids(source, FAMILY_DEEP))


def test_calls_volatile_and_goto_are_left_alone():
    assert not kids(SOURCE.replace('n += 1;', 'goto end;'))
    assert not [c for c in kids(SOURCE.replace('t = D_g * 2;', 't = h(g) * 2;'), FAMILY_DEEP) if 'h(g)' in c and 'do { do { t' in c]


def test_it_is_registered_and_bounded():
    repair = registry.get('statement_fence')
    assert repair and registry.problems(repair) == [] and set(REPAIR['families']) == {FAMILY_RUN, FAMILY_DEEP}
    assert len(variants(SOURCE, 'f')) <= LIMIT
