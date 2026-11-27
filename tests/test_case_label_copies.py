"""A shared case body written once per label, and the default-into-else moves on trailing-brace C."""
from decomprepair import case_label_copies, default_else_repairs
from decomprepair.line_scan import relaid

SOURCE = '''void f(Obj *obj, int n) {
    switch (obj->state) {
    case 1:
    case 2:
    case 3:
        if (n == 0) {
            obj->state = n;
        }
        break;
    case 4:
        g(n);
        break;
    }
}
'''


def test_each_label_gets_its_own_body():
    (family, child), = case_label_copies.variants(SOURCE, 'f')
    assert family == 'case_label_copies'
    assert child.count('obj->state = n;') == 3 and child.count('g(n);') == 1
    assert child.count('break;') == 4
    assert child.count('{') == child.count('}')


def test_a_run_that_falls_into_the_next_case_is_left_alone():
    source = SOURCE.replace('        break;\n    case 4:', '    case 4:')
    assert case_label_copies.variants(source, 'f') == []


def test_default_moves_into_an_else_with_trailing_braces():
    source = '''void f(int n) {
    int pick;

    pick = 0;
    if (n != 1) {
        pick = g() % n;
    }
    h(pick);
}
'''
    children = dict(default_else_repairs.variants(source, 'f'))
    assert 'if (n == 1)' in children['default_into_then']
    assert 'else' in children['default_into_else']


def test_relaid_leaves_its_own_layout_and_loops_alone():
    source = 'void f(int n)\n{\n  do\n  {\n    n--;\n  } while (n);\n}\n'
    assert relaid(source, 'f') == source
    assert relaid('void f(int n)\n{\n  if (n) {\n    n = 0;\n  } else {\n    n = 1;\n  }\n}\n', 'f') == (
        'void f(int n)\n{\n  if (n)\n  {\n    n = 0;\n  }\n  else\n  {\n    n = 1;\n  }\n}\n')
