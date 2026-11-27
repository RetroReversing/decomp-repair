from decomprepair.tail_guard_else import FAMILY, variants

SOURCE = """void f(void *arg0) {
    s32 var_a0;

    var_a0 = g();
    if (var_a0 != 0) {
        h(0x1B);
        if (D_B != 0) {
            D_B = 0;
            return;
        }
        D_B = 1;
    }
}
"""


def squeezed(text):
    return ''.join(text.split())


def test_both_orientations_of_a_tail_guard():
    children = variants(SOURCE, 'f')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    head = 'voidf(void*arg0){s32var_a0;var_a0=g();if(var_a0!=0){h(0x1B);'
    assert squeezed(children[0][1]) == head + 'if(D_B==0){D_B=1;}else{D_B=0;}}}'
    assert squeezed(children[1][1]) == head + 'if(D_B!=0){D_B=0;}else{D_B=1;}}}'


def test_a_statement_after_the_block_declines():
    assert variants(SOURCE.replace('        D_B = 1;\n    }\n', '        D_B = 1;\n    }\n    h(2);\n'), 'f') == []


def test_a_loop_around_the_guard_declines():
    assert variants(SOURCE.replace('if (var_a0 != 0) {', 'while (var_a0 != 0) {'), 'f') == []


def test_the_rest_of_an_if_chain_may_follow():
    chained = SOURCE.replace('        D_B = 1;\n    }\n', '        D_B = 1;\n    } else {\n        h(3);\n    }\n')
    assert len(variants(chained, 'f')) == 2


def test_a_top_level_guard_is_left_to_guard_shape():
    assert variants('void f(void) {\n    if (D_B != 0) {\n        D_B = 0;\n        return;\n    }\n    D_B = 1;\n}\n', 'f') == []
