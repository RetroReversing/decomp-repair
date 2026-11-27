from decomprepair import m2c_switch_loop, switch_arm_accumulate
from decomprepair.m2c_switch_loop import variants

M2C = """s32 draw(s32 total, u8 *text, f32 *x) {
    f32 var_fv0;
    u8 temp_v0;

loop_1:
    temp_v0 = *text;
    switch (temp_v0) {                              /* irregular */
    case 0:
        break;
    default:
        total = glyph(total, temp_v0, x);
        var_fv0 = (f32) widths[*text] + *x;
        goto block_9;
    case 32:
        var_fv0 = *x + 14.0f;
block_9:
        *x = var_fv0;
        text += 1;
        goto loop_1;
    }
    return total;
}
"""


def _child(source):
    found = variants(source, 'draw')
    return found[0][1] if found else None


def test_the_shared_tail_goes_after_the_switch_inside_a_loop():
    child = _child(M2C)
    assert 'for (;;) {' in child and 'goto loop_1' not in child and 'block_9' not in child
    assert 'case 0:\n        goto __repair_loop_exit;' in child
    assert child.index('*x = var_fv0;') > child.index('var_fv0 = *x + 14.0f;')
    assert child.index('__repair_loop_exit:') < child.index('return total;')


def test_the_arms_then_add_into_the_pointer_themselves():
    child = switch_arm_accumulate.variants(_child(M2C), 'draw')[0][1]
    assert '*x += (f32) widths[*text];' in child and '*x += 14.0f;' in child
    assert '*x = var_fv0;' not in child and 'text += 1;' in child


def test_a_switch_without_a_default_or_a_second_jump_to_the_head_is_left_alone():
    assert not variants(M2C.replace('    default:\n', '    case 5:\n'), 'draw')
    assert not variants(M2C.replace('    return total;', '    goto loop_1;'), 'draw')


def test_a_loop_inside_an_arm_or_a_branch_in_the_tail_is_left_alone():
    assert not variants(M2C.replace('total = glyph(total, temp_v0, x);', 'while (total) { total--; break; }'), 'draw')
    assert not variants(M2C.replace('text += 1;', 'if (total) text += 1;'), 'draw')


def test_accumulate_declines_a_narrower_carrier_a_regrouped_sum_and_a_later_read():
    loop = _child(M2C)
    for broken in (loop.replace('f32 var_fv0;', 's32 var_fv0;'),
                   loop.replace('var_fv0 = *x + 14.0f;', 'var_fv0 = *x + 14.0f + 1.0f;'),
                   loop.replace('var_fv0 = *x + 14.0f;', 'var_fv0 = *x - x[1];'),
                   loop.replace('return total;', 'return total + (s32) var_fv0;')):
        assert not switch_arm_accumulate.variants(broken, 'draw')
    assert m2c_switch_loop.REPAIR['order'] < switch_arm_accumulate.REPAIR['order']
