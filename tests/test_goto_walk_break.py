"""m2c's guarded walk that leaves from the middle, as a `while` with a `break`."""
from decomprepair import goto_walk_break as g

SOURCE = '''void f(Node *node) {
    found = 0;
    if (node->parent != 0) {
loop_9:
        node = node->parent;
        if (node->kind != 7) {
            if (node->parent != 0) {
                goto loop_9;
            }
        } else {
            node = node->child;
            found = 1;
        }
    }
    use(node, found);
}
'''


def test_the_walk_is_a_while_with_a_break():
    [(family, out)] = g.variants(SOURCE, 'f')
    assert family == g.FAMILY
    assert 'while (node->parent != 0) {' in out and 'if (node->kind == 7) {' in out
    assert 'break;' in out and 'goto' not in out and 'loop_9' not in out
    assert out.index('found = 1;') < out.index('break;') < out.index('use(node, found);')


def test_declined_when_it_is_another_program():
    assert g.variants(SOURCE.replace('if (node->parent != 0) {\n                goto',
                                     'if (node->child != 0) {\n                goto'), 'f') == []
    assert g.variants(SOURCE.replace('    use(node, found);', '    goto loop_9;'), 'f') == []  # a second jump
    assert g.variants(SOURCE.replace('        }\n    }\n    use', '        }\n        after();\n    }\n    use'), 'f') == []
