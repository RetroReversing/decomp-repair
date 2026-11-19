"""An assignment m2c read twice from a delay slot, computed once after the `if` as the source did."""
from decomprepair import delay_slot_duplicate_repairs as d

SOURCE = '''void f(s32 arg0) {
    s32 var_v0;

    if (arg0 != -1) {
        var_v0 = arg0 * 2;
        if (g() & 0xFF) {
            h(arg0);
            var_v0 = arg0 * 2;
        }
        k((((var_v0 + arg0) * 4) + arg0) << 5);
    }
}
'''


def test_moves_the_duplicate_after_the_if():
    # An N64 function (gcc 2.7.2 -O2): 83 of 91 instructions differed with m2c's two copies.
    (family, out), = d.variants(SOURCE, 'f')
    assert family == 'delay_slot_duplicate'
    assert '''        if (g() & 0xFF) {
            h(arg0);
        }
        var_v0 = arg0 * 2;
        k(''' in out
    assert out.count('var_v0 = arg0 * 2;') == 1


def test_left_alone_where_the_value_could_differ():
    def none(source):
        return d.variants(source, 'f') == []
    assert none(SOURCE.replace('            h(arg0);', '            arg0 = h(arg0);'))  # the arm changes an input
    assert none(SOURCE.replace('if (g() & 0xFF)', 'if (g(var_v0) & 0xFF)'))  # the condition reads it
    assert none(SOURCE.replace('            h(arg0);', '            h(var_v0);'))  # the arm reads it
    assert none(SOURCE.replace('arg0 * 2;', 'p[arg0];'))  # a load
    assert none(SOURCE.replace('arg0 * 2;', 'h(arg0);'))  # a call
    assert none(SOURCE.replace('            var_v0 = arg0 * 2;', '            var_v0 = arg0 * 3;'))  # not the same
    assert none(SOURCE.replace('        }\n        k(', '        } else {\n            h(0);\n        }\n        k('))


def test_propose_finds_the_family():
    from decomprepair.propose import propose
    assert any(p.module == 'delay_slot_duplicate_repairs' for p in propose(SOURCE, 'f').proposals)


COMPARISON = '''void f(s32 arg0, void *arg2, void *arg3) {
    s32 var_v0;

    g(arg0, 0);
    var_v0 = arg0 != 0;
    if (arg0 == D) {
        g(arg0, 9);
        var_v0 = arg0 != 0;
    }
    if ((var_v0 & (arg2 != NULL)) && (arg3 != NULL)) {
        h(arg2, arg3);
    }
}
'''


def test_a_comparison_is_moved_and_written_where_it_is_used():
    # An N64 function at 92%: m2c's `var_v0 = arg0 != 0` stayed in a saved register (`andi v0,s0,1`) until the
    # comparison was written in the condition, as the game computed it; moving it after the `if` wasn't enough.
    (_, moved), (family, inlined) = d.variants(COMPARISON, 'f')
    assert family == 'delay_slot_duplicate'
    assert '    }\n    var_v0 = arg0 != 0;\n    if ((var_v0 & (arg2 != NULL))' in moved
    assert 'var_v0' not in inlined
    assert '        g(arg0, 9);\n    }\n    if (((arg0 != 0) & (arg2 != NULL)) && (arg3 != NULL)) {' in inlined


def test_inlined_only_for_a_single_use():
    twice = COMPARISON.replace('        h(arg2, arg3);', '        h(var_v0, arg3);')
    assert len(d.variants(twice, 'f')) == 1
    changed = COMPARISON.replace('    if ((var_v0 & ', '    arg0 = k();\n    if ((var_v0 & ')
    assert len(d.variants(changed, 'f')) == 1  # its input changes before the use


def test_an_assignment_is_not_a_comparison():
    assert d.variants(COMPARISON.replace('var_v0 = arg0 != 0;', 'var_v0 = arg0 = 0;'), 'f') == []
