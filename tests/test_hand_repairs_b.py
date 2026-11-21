"""goto_shared_tail inside a switch: the tail is the label's own case, up to its `break;` or `return`."""
from decomprepair import goto_structure_repairs as g

SOURCE = '''void f(s32 arg0) {
    s32 var_a1;

    switch (arg0) {
    case 1:
        D = 0;
        var_a1 = 0x66;
        goto block_5;
    case 2:
        D = 1;
        if (E == 0) {
            var_a1 = 0x129;
        } else {
            var_a1 = 0x14D;
        }
block_5:
        g(var_a1);
        h(0x35);
        return;
    case 3:
        g(0x124);
    default:
        return;
    }
}
'''


def tails(source):
    return [text for family, text in g.variants(source, 'f') if family == 'goto_shared_tail']


def test_the_case_tail_up_to_its_return_is_copied_to_the_goto():
    # An N64 function at 82.9%: 95.5% this way, and exact after branch_call puts the tail into the if's arms.
    out = tails(SOURCE)
    assert out
    text = out[0]
    assert 'goto' not in text and 'block_5' not in text
    assert text.count('g(var_a1);') == 2 and text.count('h(0x35);') == 2
    case3 = text[text.index('case 3:'):]
    assert 'h(0x35)' not in case3  # the copy stops at the case's own return


def test_a_tail_running_into_the_next_case_is_left_alone():
    falls = SOURCE.replace('        h(0x35);\n        return;\n    case 3:', '        h(0x35);\n    case 3:')
    assert tails(falls) == []  # it continues into case 3: copying it would change what case 1 does


EXIT_TAIL = """void f(int state, int *out) {
    int value;
    switch (state) {
    case 0:
        value = 1;
        goto store;
    case 1:
        if (ready()) {
            value = 2;
store:
            (*out) = value;
        }
        goto done;
    default:
        goto done;
    }
done:
    finish();
}
"""


def test_switch_store_is_copied_with_its_exit_jump():
    (text,) = tails(EXIT_TAIL)
    assert "goto store;" not in text
    assert "{ (*out) = value; goto done; }" in text
    assert text.count("(*out) = value;") == 2


def test_switch_store_cannot_skip_work_before_its_exit():
    source = EXIT_TAIL.replace("        goto done;\n    default:", "        work();\n        goto done;\n    default:")
    assert tails(source) == []


def test_switch_store_cannot_bind_to_a_shadowing_declaration():
    source = EXIT_TAIL.replace("            value = 2;", "            int value = 2;")
    assert tails(source) == []
