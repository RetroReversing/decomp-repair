"""break_as_return: a loop's exit written as the return that follows the loop, and back."""
from decomprepair import break_as_return as br
from decomprepair import registry

BREAKS = '''s32 f(s32 max)
{
    s32 i;

    for (i = 0; i < 4; i++) {
        if (ready(i)) {
            count++;
            if (count == max) {
                break;
            }
        }
    }
    return count;
}
'''


def test_the_break_becomes_the_following_return_and_back():
    [(family, child)] = br.variants(BREAKS, 'f')
    assert family == br.BREAK
    assert child == BREAKS.replace('break;', 'return count;')
    assert br.variants(child, 'f') == [(br.RETURN, BREAKS)]


def test_inner_loops_and_switches_keep_their_breaks():
    source = '''s32 f(void)
{
    do {
        switch (state) {
        case 1:
            break;
        }
        while (busy()) {
            break;
        }
        if (done) { break; }
    } while (more());
    return obj->total;
}
'''
    assert br.variants(source, 'f') == [(br.BREAK, source.replace('{ break; }', '{ return obj->total; }'))]


def test_several_sites_together_and_alone():
    source = 'void f(void) {\n    for (;;) {\n        if (a) break;\n        if (b) break;\n        g();\n    }\n}\n'
    children = [child for family, child in br.variants(source, 'f') if family == br.BREAK]
    assert children == [source.replace('break;', 'return;'), source.replace('if (a) break;', 'if (a) return;'),
                        source.replace('if (b) break;', 'if (b) return;')]


def test_left_alone_when_the_exits_differ():
    work_after = 's32 f(void) {\n    while (x) {\n        if (y) break;\n    }\n    g();\n    return n;\n}\n'
    shadowed = 's32 f(void) {\n    while (x) {\n        s32 n = h();\n        if (n) break;\n    }\n    return n;\n}\n'
    called = 's32 f(void) {\n    while (x) {\n        if (y) break;\n    }\n    return h();\n}\n'
    bare = 's32 f(void) {\n    while (x) {\n        for (i = 0; i < 3; i++) if (y) break;\n    }\n    return n;\n}\n'
    for source in (work_after, shadowed, called, bare):
        assert br.variants(source, 'f') == []


def test_a_returned_value_that_differs_is_not_a_break():
    source = 's32 f(void) {\n    while (x) {\n        if (y) return 0;\n    }\n    return n;\n}\n'
    assert br.variants(source, 'f') == []


def test_declared_in_the_registry():
    repair = registry.get('break_as_return')
    assert repair is not None and not registry.problems(repair)
