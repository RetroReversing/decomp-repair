from decomprepair import registry
from decomprepair.priority_tie_declaration_order import FAMILY, variants

SOURCE = """void motion(void *arg0, s32 mode) {
    f32 roll;
    f32 var_s6;
    void *temp_v0;
    roll = 0.0f;
    {
    f32 var_s5;
    var_s6 = roll;
    var_s5 = roll;
    if (mode != 0) {
        var_s5 += sinAngle(1.0f);
        var_s6 += cosAngle(1.0f);
    }
    temp_v0 = arg0;
    store(temp_v0, var_s5, var_s6, roll);
    }
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'motion') if f == FAMILY]


def test_an_inner_block_local_moves_before_the_same_typed_local_it_ties_with():
    got = children()
    assert got
    first = got[0]
    assert first.index('f32 var_s5;') < first.index('f32 var_s6;') < first.index('roll = 0.0f;')
    assert first.count('f32 var_s5;') == 1
    assert '{\n    var_s6 = roll;' in first.replace('    {\n    var_s6', '{\n    var_s6')


def test_only_locals_of_the_same_type_trade_places():
    for child in children():
        assert child.count('f32 var_s5;') == 1 and child.count('f32 var_s6;') == 1
        assert child.index('void *temp_v0;') > child.index('f32 roll;')
    lone = SOURCE.replace('    f32 var_s5;\n', '    s32 var_s5;\n')
    assert all('s32 var_s5;' in c and c.index('s32 var_s5;') > c.index('roll = 0.0f;') for c in children(lone))


def test_it_declares_itself():
    assert registry.get('priority_tie_declaration_order') is not None
    assert registry.problems(registry.get('priority_tie_declaration_order')) == []
