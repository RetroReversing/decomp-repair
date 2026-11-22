from decomprepair import param_address_local_repairs as repair

WRAPPED = '''void f(void *arg0) {
  char sp18[12];
  char sp28[48];
  g(arg0);
  do { arg0 = sp18; } while (0);
  h(sp28, arg0);
  k(arg0, 4);
}
'''


def test_the_address_gets_a_local_and_later_uses_follow_it():
    out = [v for _, v in repair.variants(WRAPPED, 'f')]
    assert len(out) == 2
    dropped = next(v for v in out if 'do {' not in v)
    assert 'void *arg0_addr;' in dropped
    assert 'arg0_addr = sp18;' in dropped and 'h(sp28, arg0_addr);' in dropped and 'k(arg0_addr, 4);' in dropped
    assert 'g(arg0);' in dropped
    assert any('do { arg0_addr = sp18; } while (0);' in v for v in out)


def test_a_parameter_assigned_again_or_never_read_after_is_left_alone():
    again = repair.variants(WRAPPED.replace('  k(arg0, 4);', '  arg0 = sp28;\n  k(arg0, 4);'), 'f')
    assert not any('h(sp28, arg0_addr)' in v for _, v in again)
    assert repair.variants(WRAPPED.replace('  h(sp28, arg0);\n  k(arg0, 4);\n', ''), 'f') == []


def test_a_value_that_is_not_a_local_array_is_left_alone():
    assert repair.variants(WRAPPED.replace('arg0 = sp18;', 'arg0 = gTable;'), 'f') == []
