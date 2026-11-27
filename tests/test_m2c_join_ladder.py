"""m2c's join ladder over an unset saved register, and its halfword read of a byte table (1820 -> 510 on one update)."""
from decomprepair.m2c_join_ladder import LADDER, SAVED, TABLE, variants

SOURCE = """extern u8 table[];

void update(Obj *obj)
{
    s32 saved_reg_s2;
    s32 var_s2;
    s32 var_v1;
    u8 kind;

    obj->model = (u16) *((obj->slot * 2) + table);
    kind = obj->slot;
    if (kind == 0) {
        var_s2 = first();
        goto block_9;
    }
    if (kind == 1) {
        var_s2 = second();
        goto block_9;
    }
    var_v1 = saved_reg_s2 & 0xFF;
    if (kind == 2) {
        var_s2 = third();
block_9:
        var_v1 = var_s2 & 0xFF;
    }
    if (var_v1 == 2) {
        obj->alt = 1;
    }
}
"""

CHAIN = """    if (kind == 0) {
        var_s2 = first();
    } else if (kind == 1) {
        var_s2 = second();
    } else if (kind == 2) {
        var_s2 = third();
    }
    var_v1 = var_s2 & 0xFF;
    if (var_v1 == 2) {"""


def children(source, wanted):
    return [text for family, text in variants(source, 'update') if family == wanted]


def test_the_saved_register_is_the_local_named_for_it():
    (child,) = children(SOURCE, SAVED)
    assert 'saved_reg' not in child
    assert 'var_v1 = var_s2 & 0xFF;\n    if (kind == 2)' in child


def test_the_ladder_is_offered_with_the_rename_it_needs():
    (child,) = children(SOURCE, LADDER)
    assert CHAIN in child
    assert 'goto' not in child and 'block_9' not in child and 'saved_reg' not in child


def test_a_default_that_differs_or_is_read_by_an_arm_stays():
    other = SOURCE.replace('var_v1 = saved_reg_s2 & 0xFF;', 'var_v1 = 0;')
    assert children(other, LADDER) == []
    reading = SOURCE.replace('if (kind == 1)', 'if (var_v1 == 1)')
    assert children(reading, LADDER) == []


def test_a_label_reached_from_elsewhere_stays():
    source = SOURCE.replace('kind = obj->slot;', 'kind = obj->slot;\n    if (obj->gone) goto block_9;')
    assert children(source, LADDER) == []


def test_a_halfword_cast_of_a_byte_table_reads_the_halfword():
    (child,) = children(SOURCE, TABLE)
    assert 'obj->model = *(u16 *)((obj->slot * 2) + table);' in child
    assert children(SOURCE.replace('extern u8 table[];', 'extern u16 table[];'), TABLE) == []
    assert children(SOURCE.replace('obj->slot * 2', 'obj->slot'), TABLE) == []
