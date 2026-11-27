"""A narrow step and test written as the shift or as two statements."""
from decomprepair.narrow_step_test import variants


def _all(source):
    return [src for _, src in variants(source, 'f')]


def test_both_forms_of_a_cast_predecrement_test():
    found = _all('void f(Ctl *c) {\n  if ((s16)--c->timer == 0)\n  {\n    g();\n  }\n}\n')
    assert 'void f(Ctl *c) {\n  if ((--c->timer << 16) == 0)\n  {\n    g();\n  }\n}\n' in found
    assert 'void f(Ctl *c) {\n  c->timer--;\n  if ((s16)c->timer == 0)\n  {\n    g();\n  }\n}\n' in found


def test_an_else_if_gets_only_the_shift():
    found = _all('void f(u8 *p) { if (*p) g(); else if ((s8)++p[1] != 0) g(); }')
    assert found == ['void f(u8 *p) { if (*p) g(); else if ((++p[1] << 24) != 0) g(); }']


def test_other_conditions_are_left_alone():
    assert not _all('void f(Ctl *c) { if (--c->timer == 0) g(); }')
    assert not _all('void f(Ctl *c) { if ((s16)c->timer == 0) g(); }')
    assert not _all('void f(Ctl *c) { if ((s16)--c->timer == 0 && c->on) g(); }')
