from decomprepair import for_init_to_declaration as repair
from decomprepair import registry

SOURCE = """s8 f(s32 limit) {
    u16 j;
    u32 i;
    s8 pos = -1;

    if (mode != 0) {
        for (i = 0; i < 10; i++) {
            if (first[i] < limit) {
                pos = i;
            }
        }
    } else {
        for (i = 0; i < 10; i++) {
            if (second[i] < limit) {
                pos = i;
            }
        }
    }
    return pos;
}
"""


def test_the_start_moves_into_the_declaration_below_the_other_initialised_local():
    children = [child for family, child in repair.variants(SOURCE, 'f') if family == repair.FAMILY]
    assert len(children) == 2
    assert 'u32 i = 0;\n    s8 pos = -1;' in children[0]
    assert 's8 pos = -1;\n    u32 i = 0;' in children[1]
    assert all(child.count('for (; i < 10; i++)') == 2 for child in children)


def test_loops_that_follow_one_another_or_nest_keep_their_start():
    sequential = SOURCE.replace('    } else {\n', '    }\n    if (mode) {\n')
    assert not repair.variants(sequential, 'f')
    wrapped = SOURCE.replace('    if (mode != 0) {', '    do {\n    if (mode != 0) {').replace(
        '    return pos;', '    } while (more());\n    return pos;')
    assert not repair.variants(wrapped, 'f')


def test_a_use_before_the_loops_or_different_starts_are_left_alone():
    assert not repair.variants(SOURCE.replace('if (mode != 0) {', 'i = 3;\n    if (mode != i) {'), 'f')
    assert not repair.variants(SOURCE.replace('i = 0', 'i = 1', 1), 'f')


def test_it_is_registered():
    assert repair.FAMILY in str(registry.declared())
