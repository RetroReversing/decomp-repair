"""A switch whose arms share a tail inside the first one, written as an `else if` chain (2425 -> 210 on one update)."""
from decomprepair.switch_shared_tail_chain import FAMILY, REPAIR, variants

SOURCE = """void update(Obj *obj)
{
    s32 kind;
    s32 value;

    kind = obj->kind;
    switch (kind) {                          /* irregular */
    case 0x21:
        value = obj->pos + 8;
block_4:
        obj->pos = value;
        if (obj->kind != 0x23) {
        case 0x20:
        default:
            if (obj->pos >= 100) {
                reset(obj);
            }
        }
        break;
    case 0x22:
        value = obj->pos + 4;
        goto block_4;
    case 0x23:
        value = obj->pos + 2;
        goto block_4;
    }
}
"""


def test_chain_with_the_tail_after_it():
    (family, text), = variants(SOURCE, 'update')
    assert family == FAMILY
    squeezed = ' '.join(text.split())
    assert ('if (kind == 0x21) { value = obj->pos + 8; obj->pos = value; } else if (kind == 0x22) { '
            'value = obj->pos + 4; obj->pos = value; } else if (kind == 0x23) { value = obj->pos + 2; '
            'obj->pos = value; } if (obj->kind != 0x23) { if (obj->pos >= 100) { reset(obj); } } }') in squeezed
    assert 'switch' not in text and 'goto' not in text and 'block_4' not in text
    assert '            reset(obj);' in text
    assert REPAIR['variants'] is variants


def test_statements_before_each_jump_stay_in_their_arm():
    text = SOURCE.replace('        obj->pos = value;\n        if', '        if')
    text = text.replace('block_4:\n', 'obj->pos = value;\nblock_4:\n')
    text = text.replace('        goto block_4;', '        obj->pos = value; goto block_4;')
    (_, child), = variants(text, 'update')
    assert child.count('obj->pos = value;') == 3


def test_value_assigned_in_the_switch_head():
    text = SOURCE.replace('    kind = obj->kind;\n    switch (kind)', '    switch ((kind = obj->kind))')
    (_, child), = variants(text, 'update')
    assert 'if ((kind = obj->kind) == 0x21)' in child and 'else if (kind == 0x22)' in child


def test_leaves_shapes_that_would_change_what_runs():
    # the test is not true for a value no case names
    assert not variants(SOURCE.replace('!= 0x23', '== 0x23'), 'update')
    assert not variants(SOURCE.replace('!= 0x23', '!= 0x30'), 'update')
    # it reads something other than what the switch read
    assert not variants(SOURCE.replace('if (obj->kind != 0x23)', 'if (obj->mode != 0x23)'), 'update')
    # an arm falls into the next
    assert not variants(SOURCE.replace('value = obj->pos + 4;\n        goto block_4;', 'value = obj->pos + 4;'),
                        'update')
    # a break in the shared tail would leave the switch that goes away
    assert not variants(SOURCE.replace('reset(obj);', 'reset(obj);\n                break;'), 'update')
    # no default: a value no case names skips the tail
    assert not variants(SOURCE.replace('        default:\n', ''), 'update')
