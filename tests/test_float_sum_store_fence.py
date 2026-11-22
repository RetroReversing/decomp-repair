"""A float sum split around a run of stores: operands swapped and a one-shot scope inside the run."""
from decomprepair import float_sum_store_fence as m

SOURCE = '''void f(f32 *out, f32 *box, f32 a, f32 b, f32 c) {
    f32 x2, y2, z2, length2;
    x2 = a * a;
    y2 = b * b;
    z2 = c * c;
    length2 = y2 + x2;
    box[1] = a;
    { }
    box[3] = b;
    box[5] = c;
    length2 += z2;
    box[0] = a;
    box[2] = b;
    out[3] = length2 * 0.5f;
}
'''


def texts():
    return [text for family, text in m.variants(SOURCE, 'f')]


def test_the_swap_and_each_scope_position_alone_and_together():
    found = texts()
    assert len(found) == 1 + 2 + 2
    swapped = [t for t in found if 'length2 = x2 + y2;' in t]
    assert len(swapped) == 3
    assert sum('do { } while (0);' in t for t in found) == 4
    chain = next(t for t in swapped if 'box[3] = b;\n    do { } while (0);\nbox[5]' in t)
    assert 'length2 += z2;' in chain


def test_nothing_when_a_call_or_the_sum_is_read_between():
    assert m.variants(SOURCE.replace('box[3] = b;', 'g(length2);'), 'f') == []
    assert m.variants(SOURCE.replace('box[3] = b;', 'box[3] = length2;'), 'f') == []
    assert m.variants(SOURCE.replace('length2 += z2;', 'length2 -= z2;'), 'f') == []
