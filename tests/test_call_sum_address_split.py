from decomprepair import call_sum_address_split as repair

SOURCE = '''void f(Obj *obj) {
    Row *table;
    s32 heading;

    table = gRows;
    heading = angleOf(obj->vx, obj->vy) + 0x800;
    use(table, heading);
}
'''


def test_address_set_moves_between_the_call_and_the_sum():
    (family, text), = repair.variants(SOURCE, 'f')
    assert family == repair.FAMILY
    assert 's32 call_result;' in text
    assert ('call_result = angleOf(obj->vx, obj->vy);\n    table = gRows;\n    heading = call_result + 0x800;'
            in text)


def test_the_other_order_is_read_too():
    swapped = SOURCE.replace('    table = gRows;\n    heading = angleOf(obj->vx, obj->vy) + 0x800;\n',
                             '    heading = angleOf(obj->vx, obj->vy) + 0x800;\n    table = gRows;\n')
    assert repair.variants(swapped, 'f')[0][1] == repair.variants(SOURCE, 'f')[0][1]


def test_a_call_that_names_the_pointer_is_left():
    source = SOURCE.replace('angleOf(obj->vx, obj->vy)', 'angleOf(table, obj->vy)')
    assert repair.variants(source, 'f') == []


def test_two_calls_in_the_sum_are_left():
    source = SOURCE.replace('angleOf(obj->vx, obj->vy) + 0x800', 'angleOf(obj->vx) + other(1) + 0x800')
    assert repair.variants(source, 'f') == []
