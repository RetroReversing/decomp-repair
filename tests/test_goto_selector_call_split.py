"""goto_selector_call_split: a call behind a label, its argument in a selector local, written out on each path."""
from decomprepair import goto_selector_call_split as repair

SOURCE = """void f(void *arg0) {
    M2C_UNK var_a2;

    if (D_two != 0) {
        if (D_a != 0) {
            var_a2 = 0xCA;
            goto block_22;
        }
        if (D_b != 0) {
            g(arg0, 0xC8, 0xCB);
            if (D_c == 0) {
                var_a2 = 0xCC;
                goto block_22;
            }
        }
    } else {
        var_a2 = 0xC8;
block_22:
        g(arg0, 0xC8, var_a2);
    }
    h(arg0);
}
"""

EXPECTED = """void f(void *arg0) {

    if (D_two != 0) {
        if (D_a != 0) {
            g(arg0, 0xC8, 0xCA);
        } else if (D_b != 0) {
            g(arg0, 0xC8, 0xCB);
            if (D_c == 0) {
                g(arg0, 0xC8, 0xCC);
            }
        }
    } else {
        g(arg0, 0xC8, 0xC8);
    }
    h(arg0);
}
"""


def test_the_shared_call_is_made_on_each_path():
    assert repair.variants(SOURCE, 'f') == [('goto_selector_call_split', EXPECTED)]


def test_several_statements_after_a_guard_become_a_braced_else():
    source = SOURCE.replace("        if (D_b != 0) {", "        D_d = 1;\n        if (D_b != 0) {")
    (_, child), = repair.variants(source, 'f')
    assert '} else {\n            D_d = 1;\n            if (D_b != 0) {' in child
    assert 'goto' not in child


def test_declines_when_the_selector_is_read_elsewhere():
    assert repair.variants(SOURCE.replace('h(arg0);', 'h(var_a2);'), 'f') == []


def test_work_after_a_guard_goes_in_its_else_and_work_after_the_arm_declines():
    inside = SOURCE.replace("                goto block_22;\n            }\n        }\n",
                            "                goto block_22;\n            }\n            k();\n        }\n")
    (_, child), = repair.variants(inside, 'f')
    assert 'g(arg0, 0xC8, 0xCC);\n            } else {\n                k();\n            }' in child
    # a statement after the block that holds the jumps would run on the jump's path too: nothing is offered
    after = SOURCE.replace("        }\n    } else {\n", "        }\n        k();\n    } else {\n")
    assert repair.variants(after, 'f') == []


def test_declines_a_jump_outside_the_chain():
    source = SOURCE.replace('    h(arg0);', '    if (D_e) {\n        var_a2 = 1;\n        goto block_22;\n    }\n    h(arg0);')
    assert repair.variants(source, 'f') == []


TAIL = '''void banner(s32 arg0) {
    s32 var_a1;

    if (two == 0) {
        format(arg0);
        var_a1 = 0x7D;
        goto block_9;
    }
    if (won != 0) {
        draw(arg0, 0x50, 1);
        return;
    }
    if (many != 0) {
        format(1);
        var_a1 = 0x5F;
block_9:
        draw(arg0, var_a1, 1);
    }
}
'''


def test_a_call_that_ends_a_void_function_is_made_on_each_path():
    [(_, child)] = repair.variants(TAIL, 'banner')
    assert '        format(arg0);\n        draw(arg0, 0x7D, 1);\n        return;\n    }' in child
    assert '        format(1);\n        draw(arg0, 0x5F, 1);\n    }' in child
    assert 'var_a1' not in child and 'goto' not in child and 'block_9' not in child


def test_a_selector_read_elsewhere_keeps_the_shared_call():
    assert repair.variants(TAIL.replace('draw(arg0, 0x50, 1);', 'draw(arg0, var_a1, 1);'), 'banner') == []


def test_a_call_with_code_after_it_keeps_the_shared_call():
    assert repair.variants(TAIL.replace('draw(arg0, var_a1, 1);\n    }', 'draw(arg0, var_a1, 1);\n    }\n    done();'), 'banner') == []
