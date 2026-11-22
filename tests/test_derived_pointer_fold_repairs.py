from decomprepair.derived_pointer_fold_repairs import FAMILY, variants

SOURCE = '''void f(u16 *start, s32 count)
{
    u16 *rec;
    u16 *field;
    rec = start;
    field = rec + 0x1E;
    do {
        use(M2C_FIELD(field, u16 *, -0x18), M2C_FIELD(field, s32 *, 0), M2C_FIELD(rec, u16 *, 0));
        rec += 0x22;
        field = rec + 0x1E;
        count -= 1;
    } while (count > 0);
}
'''


def folded(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_second_base_becomes_offsets_from_the_first():
    text, = folded()
    assert 'use(M2C_FIELD(rec, u16 *, 0x24), M2C_FIELD(rec, s32 *, 0x3C), M2C_FIELD(rec, u16 *, 0));' in text
    assert 'field' not in text
    assert 'rec += 0x22;\n        count -= 1;' in text


def test_a_second_pointer_that_moves_on_its_own_stays():
    assert not folded(SOURCE.replace('rec += 0x22;\n        field = rec + 0x1E;', 'rec += 0x22;\n        field += 3;'))


def test_a_write_of_the_first_pointer_without_the_update_stays():
    assert not folded(SOURCE.replace('field = rec + 0x1E;\n        count', 'count'))


def test_a_use_that_is_not_a_field_read_stays():
    assert not folded(SOURCE.replace('M2C_FIELD(field, s32 *, 0)', 'field[3]'))
