"""A constant-folded entry value computed from a fenced variable keeps the derived shift."""
from decomprepair import folded_entry_fence as p

SOURCE = '''typedef int s32;
extern s32 table[];

s32 f(s32 key) {
    s32 var_a1;
    s32 var_v1;

    var_a1 = 0 * 8;
    var_v1 = 0;
loop_1:
    if (key != table[var_a1]) {
        var_v1 += 1;
        var_a1 = var_v1 * 8;
        if (var_v1 >= 0xA) {
            return -1;
        }
        goto loop_1;
    }
    return table[var_a1 + 1];
}
'''


def test_the_folded_value_follows_the_entry_variable_inside_a_fence():
    children = p.variants(SOURCE, 'f')
    assert [family for family, _ in children] == [p.FAMILY]
    assert '    do { var_v1 = 0; } while (0);\n    var_a1 = var_v1 * 8;\nloop_1:' in children[0][1]
    assert 'var_a1 = 0 * 8' not in children[0][1]


def test_the_entry_assignment_may_come_first():
    source = SOURCE.replace('    var_a1 = 0 * 8;\n    var_v1 = 0;\n', '    var_v1 = 0;\n    var_a1 = 0 * 8;\n')
    children = p.variants(source, 'f')
    assert '    do { var_v1 = 0; } while (0);\n    var_a1 = var_v1 * 8;\nloop_1:' in children[0][1]


def test_the_literal_may_be_the_right_operand_and_another_value_is_left_alone():
    source = SOURCE.replace('0 * 8', '8 << 0').replace('var_v1 = 0;', 'var_v1 = 0;', 1)
    assert 'var_a1 = 8 << var_v1;' in p.variants(source, 'f')[0][1]
    assert p.variants(SOURCE.replace('var_v1 = 0;', 'var_v1 = 3;', 1), 'f') == []
    assert p.variants(SOURCE.replace('var_a1 = 0 * 8;', 'var_a1 = 0 * 8;\n    key = 1;'), 'f') == []
