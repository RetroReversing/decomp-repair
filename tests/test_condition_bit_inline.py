"""m2c's saved FP condition written where it is tested (a 1137-instruction player update, 3871 -> 2651)."""
from decomprepair.condition_bit_inline import FAMILY, REPAIR, variants

SOURCE = """void update(Obj *o)
{
    s32 var_condition_bit;
    f32 var_fs0;
    var_fs0 = o->speed;
    if (o->flags & 4) {
        var_fs0 = 1.0f;
    }
    var_condition_bit = var_fs0 > 0.0f;
    o->pos = o->next;
    if ((var_fs0 > 0.0f) && (o->mode == 2)) {
        play(o);
        block_95:
        var_condition_bit = var_fs0 > 0.0f;
    }
    if (var_condition_bit) {
        o->hits += 1;
    }
}
"""


def children(source):
    return [text for family, text in variants(source, 'update') if family == FAMILY]


def test_the_assignments_and_the_declaration_go_and_the_test_compares():
    found = children(SOURCE)
    assert len(found) == 1
    child = found[0]
    assert 'condition_bit' not in child
    assert '    if (var_fs0 > 0.0f) {\n        o->hits += 1;' in child
    # the label that held an assignment still has a statement
    assert 'block_95:\n        ;\n    }' in child or 'block_95:\n        ;' in child
    assert '    o->pos = o->next;\n' in child


def test_a_negated_test_keeps_the_negation():
    child = children(SOURCE.replace('if (var_condition_bit) {', 'if (!var_condition_bit) {'))[0]
    assert 'if (!(var_fs0 > 0.0f)) {' in child


def test_an_operand_written_between_keeps_the_local():
    source = SOURCE.replace('    o->pos = o->next;\n', '    var_fs0 = o->other;\n')
    assert children(source) == []


def test_assignments_of_different_expressions_are_left_alone():
    source = SOURCE.replace('        block_95:\n        var_condition_bit = var_fs0 > 0.0f;', '        block_95:\n        var_condition_bit = var_fs0 >= 0.0f;')
    assert children(source) == []


def test_another_use_of_the_local_is_left_alone():
    source = SOURCE.replace('o->hits += 1;', 'o->hits += var_condition_bit;')
    assert children(source) == []


def test_a_call_in_the_expression_is_left_alone():
    source = SOURCE.replace('var_condition_bit = var_fs0 > 0.0f;', 'var_condition_bit = probe(var_fs0);')
    assert children(source) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
