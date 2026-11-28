"""m2c's join ladder over an unset saved register, and its halfword read of a byte table (1820 -> 510 on one update)."""
from decomprepair.m2c_join_ladder import CHAIN as ARM_CHAINS
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


ARM_CHAIN = """extern s32 total;

void setup(s32 mode)
{
    s32 var_v0;

    if (mode == 0) {
        var_v0 = 0x1F40;
        goto block_14;
    }
    if (mode == 1) {
        var_v0 = 0x2EE0;
        goto block_14;
    }
    if (mode == 2) {
        var_v0 = 0x3E80;
block_14:
        total = var_v0;
    }
}
"""


def chain_children(source):
    return [text for family, text in variants(source, 'setup') if family == ARM_CHAINS]


def test_arms_jumping_into_the_last_arm_write_its_statement_themselves():
    carried, copied = chain_children(ARM_CHAIN)
    assert """    if (mode == 0) {
        total = 0x1F40;
    } else if (mode == 1) {
        total = 0x2EE0;
    } else if (mode == 2) {
        total = 0x3E80;
    }
}""" in carried
    assert """    if (mode == 0) {
        var_v0 = 0x1F40;
        total = var_v0;
    } else if (mode == 1) {""" in copied
    assert 'goto' not in carried + copied


def test_a_local_read_again_is_not_replaced_by_its_constant():
    source = ARM_CHAIN.replace('        total = var_v0;\n    }\n', '        total = var_v0;\n    }\n    use(var_v0);\n')
    only, = chain_children(source)
    assert 'total = var_v0;' in only and 'use(var_v0);' in only


def test_a_jump_from_elsewhere_keeps_the_label():
    source = ARM_CHAIN.replace('    if (mode == 0) {', '    if (mode > 9) {\n        goto block_14;\n    }\n'
                               '    work();\n    if (mode == 0) {', 1)
    assert not chain_children(source)


def test_argument_register_read_as_the_default_is_the_local():
    from decomprepair.m2c_join_ladder import ARGUMENT

    source = (SOURCE.replace('void update(Obj *obj)', 'void update(Obj *obj, s32 arg1)')
              .replace('saved_reg_s2 & 0xFF', 'arg1 & 0xFF').replace('var_s2', 'var_a1'))
    text, = children(source, ARGUMENT)
    assert 'void update(Obj *obj)' in text and 'arg1' not in text
    assert 'goto' not in text and 'var_v1 = var_a1 & 0xFF;' in text


def test_a_parameter_with_another_use_stays():
    from decomprepair.m2c_join_ladder import ARGUMENT

    source = (SOURCE.replace('void update(Obj *obj)', 'void update(Obj *obj, s32 arg1)')
              .replace('saved_reg_s2 & 0xFF', 'arg1 & 0xFF').replace('var_s2', 'var_a1')
              .replace('obj->alt = 1;', 'obj->alt = arg1;'))
    assert children(source.replace('obj->alt = arg1;', 'send(arg1);'), ARGUMENT) == []


def test_a_label_before_many_statements_does_not_backtrack():
    from decomprepair.m2c_join_ladder import _goto_arm_chain

    arm = '    if (a) {\nL:\n' + '        x->field = 1;\n' * 60 + '        if (b) {\n        }\n    }\n'
    assert _goto_arm_chain('{\n' + arm + '}\n') == []
