from decomprepair import index_zero_in_declaration as repair
from decomprepair import registry

SOURCE = """void f(s32 page) {
    f32 limit = 0.0f;
    u8 **lines = NULL;
    s32 i;

    if (page == 0) {
        lines = first;
    } else if (page == 1) {
        lines = second;
    }
    i = 0;
    while (compare(END, lines[i]) != 0) {
        draw(lines[i]);
        i++;
    }
}
"""

WALK = """void f(s32 page) {
    M2C_UNK *var_a0;
    s32 var_s1;
    u8 **var_s0;

    var_s1 = 0;
    var_a0 = page ? &first : &second;
    var_s0 = (0 * 4) + var_a0;
loop_1:
    if (compare(END, *var_s0) != 0) {
        draw(*var_s0, var_s1);
        var_s0 += 4;
        var_s1 += 0xA;
        goto loop_1;
    }
}
"""


def _children(source, family):
    return [child for found, child in repair.variants(source, 'f') if found == family]


def test_the_zero_moves_above_the_branches_into_the_declaration():
    children = _children(SOURCE, repair.FAMILY)
    assert len(children) == 1
    assert 's32 i = 0;' in children[0]
    assert '\n    i = 0;' not in children[0]
    assert 'i++;' in children[0]


def test_an_index_used_before_its_zero_or_with_no_branch_before_it_is_left_alone():
    assert not _children(SOURCE.replace('if (page == 0) {', 'draw(i);\n    if (page == 0) {'), repair.FAMILY)
    straight = SOURCE[:SOURCE.index('    if (page')] + SOURCE[SOURCE.index('    i = 0;'):]
    assert not _children(straight, repair.FAMILY)
    assert not _children(SOURCE.replace('    i = 0;\n', '    if (page) {\n        i = 0;\n    }\n'), repair.FAMILY)


def test_the_literal_zero_index_walk_becomes_an_index_from_the_declaration():
    children = _children(WALK, repair.WALK_FAMILY)
    assert len(children) == 1
    child = children[0]
    assert 's32 var_s0_index = 0;' in child
    assert 'u8 **var_s0;' not in child and '(0 * 4)' not in child
    assert child.count('((u8 **)var_a0)[var_s0_index]') == 2
    assert 'var_s0_index++;' in child


def test_a_walk_with_another_use_or_another_step_is_left_alone():
    assert not _children(WALK.replace('var_s0 += 4;', 'var_s0 += 8;'), repair.WALK_FAMILY)
    assert not _children(WALK.replace('draw(*var_s0, var_s1);', 'draw(var_s0, var_s1);'), repair.WALK_FAMILY)


def test_the_module_is_registered():
    assert registry.get(repair.__name__.split(".")[-1]) or registry.get(repair.__name__)
