from decomprepair import masked_countdown_for as repair
from decomprepair import registry

SOURCE = """void f(u32 var_s1) {
    s32 var_s0;
    s32 var_v0;

    var_s0 = 9;
    if (var_s1 < 9U) {
        var_v0 = 9 & 0xFFFF;
        do {
            temp = var_v0 * 4;
            var_s0 -= 1;
            table[var_v0] = table[var_v0 - 1];
            g(temp);
            var_v0 = var_s0 & 0xFFFF;
        } while (var_s1 < (u32) (var_s0 & 0xFFFF));
    }
}
"""


def test_the_countdown_becomes_a_for_over_a_narrow_counter():
    (family, child), = repair.variants(SOURCE, 'f')
    assert family == repair.FAMILY
    assert 'u16 var_s0;' in child and 'var_v0' not in child
    assert 'for (var_s0 = 9; var_s1 < var_s0; var_s0--) {\n        temp = var_s0 * 4;\n        table[var_s0]' in child
    assert 'do {' not in child and '-= 1' not in child


def test_a_counter_read_beside_its_step_or_after_the_loop_is_left_alone():
    assert not repair.variants(SOURCE.replace('g(temp);', 'g(var_s0);'), 'f')
    assert not repair.variants(SOURCE.replace('    }\n}\n', '    }\n    g(var_s0);\n}\n'), 'f')
    assert not repair.variants(SOURCE.replace('var_s1 < 9U', 'var_s1 < 8U'), 'f')


def test_it_is_registered():
    assert repair.FAMILY in str(registry.declared())
