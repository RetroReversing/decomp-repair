"""Case labels opened inside an arm's `else`, written as arms of their own."""
from decomprepair import else_case_arm_lift

SOURCE = '''void f(Obj *obj, int mode) {
    int i;

    for (i = 0; i < obj->count; i++) {
        switch (obj->type) {
        case 4:
        case 8:
            if (mode == 5) {
                obj->type = 8;
            } else {
            case 1:
            case 6:
            case 7:
                obj->count++;
            }
            break;
        case 2:
        case 5:
            obj->score++;
            break;
        }
    }
}
'''


def test_every_label_gets_its_own_arm_in_the_first_child():
    family, child = else_case_arm_lift.variants(SOURCE, 'f')[0]
    assert family == 'else_case_arm_lift'
    # the else keeps one copy, the three lifted labels get one each
    assert child.count('obj->count++;') == 4
    # the other stacked run of the switch is copied too
    assert child.count('obj->score++;') == 2
    assert 'case 4:\n        case 8:' in child
    assert child.count('{') == child.count('}')
    assert child.count('break;') == 6
    # the lifted copies are the switch's last arms
    assert child.index('case 5:') < child.index('case 1:') < child.index('case 7:')


def test_partial_children():
    children = [child for _, child in else_case_arm_lift.variants(SOURCE, 'f')]
    assert len(children) == 4
    assert children[1].index('case 7:') < children[1].index('case 2:')
    assert children[2].count('obj->count++;') == 4 and children[2].count('obj->score++;') == 1
    assert children[3].count('obj->count++;') == 2


def test_a_switch_whose_last_arm_runs_off_gets_a_break_before_the_new_arms():
    source = SOURCE.replace('            obj->score++;\n            break;\n', '            obj->score++;\n')
    last = else_case_arm_lift.variants(source, 'f')[-2][1]
    assert 'obj->score++;\n            break;\n        case 1:' in last


def test_an_else_that_is_not_the_end_of_its_arm_is_left_alone():
    source = SOURCE.replace('            }\n            break;\n        case 2:',
                            '            }\n            obj->score = 0;\n            break;\n        case 2:')
    assert else_case_arm_lift.variants(source, 'f') == []


def test_a_labelled_or_declaring_body_is_left_alone():
    for body in ('again:\n                obj->count++;', 'int n = 1;\n                obj->count += n;'):
        assert else_case_arm_lift.variants(SOURCE.replace('obj->count++;', body), 'f') == []
