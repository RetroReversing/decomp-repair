from decomprepair import registry
from decomprepair.flag_local_negated_mask import FAMILY, REPAIR, variants

SOURCE = """void f(void *arg0) {
    s32 var_s1;
    var_s1 = g();
    if (var_s1 != 0) {
        var_s1 &= -((*(u8 *)((s8 *)arg0 + 0x50)) != 0);
    } else {
        var_s1 &= -(h(arg0) < 3);
    }
}
"""


def _children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_each_negated_comparison_is_held_in_a_block_local_then_all_together():
    kids = _children()
    assert len(kids) == 3
    one = '{ s32 flag = (*(u8 *)((s8 *)arg0 + 0x50)) != 0; var_s1 &= -flag; }'
    two = '{ s32 flag = h(arg0) < 3; var_s1 &= -flag; }'
    assert one in kids[0] and '&= -(h(arg0) < 3);' in kids[0]
    assert two in kids[1] and '&= -((*(u8' in kids[1]
    assert one in kids[2] and two in kids[2]


def test_a_taken_name_gets_a_suffix_and_non_comparisons_are_left():
    assert '{ s32 flag2 = ' in _children(SOURCE.replace('s32 var_s1;', 's32 var_s1, flag;'))[0]
    plain = 'void f(int v, int *p) {\n    v &= -(p[0]);\n    v &= -(p[0] != 0 && p[1] != 0);\n    v &= -(v = 3);\n}\n'
    assert _children(plain) == []


def test_it_is_declared_for_the_callers():
    assert registry.problems(registry.get('flag_local_negated_mask')) == []
    assert FAMILY in REPAIR['families']
