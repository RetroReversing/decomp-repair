from decomprepair import identical_arm_split as repair

ARM = '''        D_A = 0;
        D_B = 0;
        D_C = 0;
        D_X = D_Y;
        D_Z = D_W;
        i = 0;
'''
SOURCE = '''void f(void)
{
  if (m)
  {
''' + ARM + '''  }
  else
  {
''' + ARM + '''  }
  g();
}
'''


def _norm(text):
    return ' '.join(text.split())


def test_the_runs_and_the_tail_of_one_identical_guard_come_out_as_one_child():
    found = repair.variants(SOURCE, 'f')
    assert found and all(family == 'identical_arm_split' for family, _ in found)
    want = _norm('if (m) { D_A = 0; D_B = 0; D_C = 0; } else { D_A = 0; D_B = 0; D_C = 0; } '
                 'if (m) { D_X = D_Y; D_Z = D_W; } else { D_X = D_Y; D_Z = D_W; } i = 0; g();')
    spaced = lambda t: _norm(t.replace('{', ' { ').replace('}', ' } '))
    assert any(spaced(want) in spaced(text) for _, text in found)


def test_every_child_is_the_same_program_as_the_arm():
    for _, text in repair.variants(SOURCE, 'f'):
        flat = _norm(text.replace('{', ' ').replace('}', ' '))
        assert flat.count('D_A = 0;') in (1, 2) and 'i = 0;' in flat and flat.endswith('g();')
        assert text.count('else') == text.count('if (m)')


def test_different_arms_impure_conditions_and_single_statements_are_left_alone():
    assert not repair.variants(SOURCE.replace('D_A = 0;\n        D_B = 0;\n        D_C = 0;\n        D_X = D_Y;\n        D_Z = D_W;\n        i = 0;\n  }\n  g', 'x = 1;\n  }\n  g', 1), 'f')
    assert not repair.variants(SOURCE.replace('if (m)', 'if (k())'), 'f')
    assert not repair.variants(SOURCE.replace('if (m)', 'if (m = n)'), 'f')
    one = 'void f(void)\n{\n  if (m)\n  {\n    a = 1;\n  }\n  else\n  {\n    a = 1;\n  }\n}\n'
    assert not repair.variants(one, 'f')
