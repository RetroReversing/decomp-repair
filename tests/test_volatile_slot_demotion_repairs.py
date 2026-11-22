from decomprepair.volatile_slot_demotion_repairs import FAMILY, variants

SOURCE = '''void f(s32 n)
{
    struct {
        f32 a, b;
        u8 pad8[8];
        volatile s32 result;
        u8 padD0[4];
        u16 *volatile buffer;
        u8 padD8[4];
        f32 *volatile where;
        u8 padE0[24];
    } L;
    s32 i;
    L.result = first(n);
    L.buffer = alloc(n);
    i = 0;
    if (n > 0) {
        L.where = &L.b;
        do {
            use(L.buffer, L.where);
            i += 1;
        } while (i < n);
    }
    done(L.result);
    free(L.buffer);
}
'''


def demoted(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_volatile_slots_become_locals_and_the_struct_ends_at_its_real_members():
    text = demoted()[0]
    head = text.split('} L;')[0]
    assert 'volatile' not in text and 'padD0' not in text and 'padE0' not in text
    assert head.rstrip().endswith('f32 a, b;')
    assert 'pad8' not in head          # the padding before the first volatile member goes too
    assert '    s32 __repair_slot_result;\n    u16 *__repair_slot_buffer;\n' in text
    assert '__repair_slot_result = first(n);' in text and 'done(__repair_slot_result);' in text
    assert 'use(__repair_slot_buffer, &L.b);' in text and 'L.where' not in text


def test_the_address_member_is_kept_apart_from_the_others():
    texts = demoted()
    assert len(texts) == 2
    assert 'volatile f32 *where' not in texts[1]
    assert 'where' in texts[1] and '__repair_slot_where' not in texts[1]


def test_a_struct_without_volatile_members_is_left_alone():
    assert not demoted(SOURCE.replace('volatile ', '').replace('u16 *volatile', 'u16 *'))


def test_a_volatile_member_assigned_twice_is_left_alone():
    assert not demoted(SOURCE.replace('done(L.result);', 'L.result = 2;\n    done(L.result);'))


def test_members_that_are_all_plain_values_give_one_variant():
    text = SOURCE.replace('        f32 *volatile where;\n', '').replace('        L.where = &L.b;\n', '').replace('use(L.buffer, L.where);', 'use(L.buffer);')
    assert len(demoted(text)) == 1
