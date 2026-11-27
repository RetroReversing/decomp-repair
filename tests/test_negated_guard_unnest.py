from decomprepair.negated_guard_unnest import variants

NEST = """extern int G;
extern int D;

void f(void) {
    if (G == 1) {
        D = 5;
        return;
    }
    if (G != 3) {
        if (G != 4) {
            if (G == 5) {
                D = 4;
                return;
            }
            return;
        }
        D = 3;
        return;
    }
    D = 1;
}
"""

FLAT = """extern int G;
extern int D;

void f(void) {
    if (G == 1) {
        D = 5;
        return;
    }
    if (G == 3) {
        D = 1;
        return;
    }
    if (G == 4) {
        D = 3;
        return;
    }
    if (G == 5) {
        D = 4;
        return;
    }
    return;
}
"""


def test_whole_nest_becomes_the_ordered_chain():
    children = variants(NEST, 'f')
    assert children[0] == ('negated_guard_unnest', FLAT)
    assert len(children) == 2  # one exchange, and both


def test_value_function_needs_a_returning_tail():
    source = "int f(int a) {\n    if (a != 0) {\n        if (a == 1) {\n            return 2;\n        }\n        return 3;\n    }\n    a++;\n}\n"
    assert variants(source, 'f') == []


def test_ordered_comparison_is_negated_whole():
    source = "void f(float a) {\n    if (a < 1) {\n        if (a == 0) {\n            g();\n        }\n        return;\n    }\n    h();\n}\n"
    assert 'if (!(a < 1)) {' in variants(source, 'f')[0][1]


def test_labels_and_else_are_left_alone():
    source = "void f(int a) {\n    if (a != 0) {\n        if (a) {\n            g();\n        }\n        return;\n    }\nout:\n    h();\n}\n"
    assert variants(source, 'f') == []
