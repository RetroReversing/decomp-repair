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
