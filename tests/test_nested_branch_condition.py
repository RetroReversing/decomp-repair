from decomprepair import nested_branch_condition

ARMS = '''f32 clamp(f32 g, f32 h)
{
    if (g > 0.0f) {
        if (g < 0.00001f) {
            g = 0.0f;
        }
    } else {
        if (-g < 0.00001f) {
            g = 0.0f;
        }
    }
    if (!(h > 0.0f)) {
        if ((-h) < 0.00001f) {
            goto block_6;
        }
    }
    else if (h < 0.00001f) {
        block_6:
        h = 0.0f;
    }
    return g + h;
}
'''


def children(source):
    return [child for _, child in nested_branch_condition.variants(source, 'clamp')]


def test_both_clamps_as_one_child():
    first = children(ARMS)[0]
    assert 'if ((g > 0.0f) ? (g < 0.00001f) : (-g < 0.00001f)) {\n        g = 0.0f;\n    }' in first
    assert 'if ((h > 0.0f) ? (h < 0.00001f) : ((-h) < 0.00001f)) {\n        h = 0.0f;\n    }' in first
    assert 'goto' not in first and 'block_6' not in first


def test_absolute_value_child_and_single_sites():
    out = children(ARMS)
    assert 'if (((g > 0.0f) ? g : -g) < 0.00001f) {' in out[1]
    assert 'if (((h > 0.0f) ? h : -h) < 0.00001f) {' in out[1]
    assert len(out) == 4


def test_different_arms_are_left():
    assert not children(ARMS.replace('g = 0.0f;', 'g = 1.0f;', 1).split('    if (!(h')[0] + '    return g;\n}\n')


def test_an_inner_else_or_a_shared_label_is_left():
    other = '''int clamp(int a, int b)
{
    if (a) {
        if (b) { b = 0; } else { b = 1; }
    } else {
        if (a < b) { b = 0; }
    }
    if (a) {
        if (b) goto done;
    } else if (a < b) {
done:
        b = 0;
    }
    if (!a) goto done;
    return b;
}
'''
    assert not children(other)
