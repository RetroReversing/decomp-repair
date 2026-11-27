"""Both bounds of a range test in narrow locals; and a narrowing cast's comparison with a load written the other way."""
from decomprepair import computed_compare_flip, range_bound_locals

SOURCE = '''void f(Obj *obj) {
    s16 x;
    u32 w;

    x = obj->x;
    w = obj->size;
    if (((s16) (w + 0xC000) < x) && (x < (s16) (0x4000 - w))) {
        g(1);
    }
    var = w + 0x4000;
    if ((s16) var < M2C_FIELD(obj, s16 *, 0)) {
        g(2);
    }
}
'''


def test_both_bounds_move_to_locals_together():
    out = range_bound_locals.variants(SOURCE, 'f')
    assert [family for family, _ in out] == ['range_bound_locals']
    text = out[0][1]
    assert 's16 range_low;' in text and 's16 range_high;' in text
    assert ('    range_low = w + 0xC000;\n    range_high = 0x4000 - w;\n'
            '    if ((range_low < x) && (x < range_high)) {') in text


def test_a_bound_with_a_call_or_a_different_operand_is_left_alone():
    assert not range_bound_locals.variants(SOURCE.replace('0x4000 - w))', 'h(w)))'), 'f')
    assert not range_bound_locals.variants(SOURCE.replace('&& (x < ', '&& (w < '), 'f')
    assert not range_bound_locals.variants(SOURCE.replace('(s16) (0x4000 - w)', '(0x4000 - w)'), 'f')


def test_a_taken_name_gets_another():
    out = range_bound_locals.variants(SOURCE.replace('u32 w;', 'u32 w;\n    s32 range_low;'), 'f')
    assert 's16 range_low_2;' in out[0][1] and 'range_low_2 = w + 0xC000;' in out[0][1]


def test_a_narrowed_value_against_a_field_read_is_flipped():
    texts = [text for family, text in computed_compare_flip.variants(SOURCE, 'f')]
    assert any('if (M2C_FIELD(obj, s16 *, 0) > (s16) var) {' in text for text in texts)
    member = SOURCE.replace('(s16) var < M2C_FIELD(obj, s16 *, 0)', '(s16) (w + 0x4000) < obj->x')
    texts = [text for family, text in computed_compare_flip.variants(member, 'f')]
    assert any('if (obj->x > (s16) (w + 0x4000)) {' in text for text in texts)
