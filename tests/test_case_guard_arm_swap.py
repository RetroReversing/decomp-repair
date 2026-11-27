from decomprepair.case_guard_arm_swap import FAMILY, variants

SOURCE = """void f(Rec *p, s32 k) {
    switch (k) {
    case 1:
        if (p->a >= p->b) {
            p->x = 1;
            return;
        }
        p->y = 2;
        return;
    case 2:
        break;
    }
    p->z = 0;
}
"""
LABEL_INSIDE = """void f(Rec *p, s32 k) {
    switch (k) {
    case 4:
        if (p->a >= p->b) {
            p->x = 1;
    case 3:
            return;
        }
        p->y = 2;
        return;
    }
}
"""
BARE_BLOCKS = """void f(Rec *p, s32 k) {
    switch (k) {
    case 2:
        {
            { if (p->a >= p->b) { p->x = 1; return; } } p->w = p->c;
        }
        p->y = p->w;
        {
            return;
        }
    }
}
"""


def squeezed(text):
    return ''.join(text.split())


def test_the_arm_and_the_rest_of_the_case_change_places():
    children = variants(SOURCE, 'f')
    assert [family for family, _ in children] == [FAMILY]
    assert squeezed(children[0][1]) == ('voidf(Rec*p,s32k){switch(k){case1:if(!(p->a>=p->b)){p->y=2;return;}p->x=1;return;'
                                        'case2:break;}p->z=0;}')


def test_a_case_label_inside_the_arm_moves_out_with_it():
    child = variants(LABEL_INSIDE, 'f')[0][1]
    assert squeezed(child) == ('voidf(Rec*p,s32k){switch(k){case4:if(!(p->a>=p->b)){p->y=2;return;}p->x=1;case3:return;}}')


def test_bare_blocks_around_the_guard_are_opened_first():
    child = variants(BARE_BLOCKS, 'f')[0][1]
    assert squeezed(child).startswith('voidf(Rec*p,s32k){switch(k){case2:if(!(p->a>=p->b)){p->w=p->c;p->y=p->w;')
    assert squeezed(child).endswith('}p->x=1;return;}}')


def test_two_cases_give_one_child_each_and_one_with_both():
    two = SOURCE.replace('    case 2:\n        break;\n', '    case 2:\n        if (p->c) {\n            return;\n        }\n'
                         '        p->y = 3;\n        break;\n')
    assert len(variants(two, 'f')) == 3


def test_a_side_that_falls_into_the_next_case_declines():
    assert variants(SOURCE.replace('        p->y = 2;\n        return;\n', '        p->y = 2;\n'), 'f') == []
    assert variants(SOURCE.replace('        p->y = 2;\n        return;\n', '        if (p->c) return;\n'), 'f') == []
    assert variants(SOURCE.replace('            p->x = 1;\n            return;\n', '            p->x = 1;\n'), 'f') == []


def test_a_guard_outside_a_switch_is_left_to_others():
    assert variants('void f(s32 k) {\n    if (k) {\n        return;\n    }\n    g();\n    return;\n}\n', 'f') == []
