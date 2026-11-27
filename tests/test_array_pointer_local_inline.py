from decomprepair import array_pointer_local_inline as inline
from decomprepair import entry_parameter_copy_repairs, local_web_split

SOURCE = '''extern u16 D_table[];

s32 func(Voice *voice, s32 value) {
    s16 *tbl;
    s32 res;

    res = value;
    while (voice->next != NULL) {
        tbl = (s16 *) D_table;
        voice->left = ((u16 *) tbl)[voice->pan];
        voice->right = tbl[0x7F - voice->pan];
        voice->next = voice->next->next;
    }
    return res;
}
'''


def test_pointer_to_an_array_is_written_as_the_array():
    [(family, text)] = inline.variants(SOURCE, 'func')
    assert family == 'array_pointer_local_inline'
    assert 'tbl' not in text
    assert 'voice->left = D_table[voice->pan];' in text
    assert 'voice->right = ((s16 *) D_table)[0x7F - voice->pan];' in text


def test_stepped_or_reassigned_pointer_is_left_alone():
    assert not inline.variants(SOURCE.replace('voice->next = voice->next->next;', 'tbl++;'), 'func')
    assert not inline.variants(SOURCE.replace('voice->next = voice->next->next;', 'tbl = other;'), 'func')
    assert not inline.variants(SOURCE.replace('voice->next = voice->next->next;', 'use(&tbl);'), 'func')


MEMBER_ADDRESS = '''void func(Voice *voice) {
    Note *note;

    switch (voice->kind) {
    case 0:
        note = voice->head;
        voice->rate = *(f32 *) &note->value;
        break;
    case 1:
        note = voice->head;
        use(note->value);
        break;
    }
    voice->time = *(s32 *) &voice->head->value;
}
'''


def test_a_members_address_is_not_the_pointers_own():
    assert local_web_split.variants(MEMBER_ADDRESS, 'func')
    assert entry_parameter_copy_repairs.variants(MEMBER_ADDRESS, 'func')


def test_the_pointers_own_address_still_declines():
    assert not local_web_split.variants(MEMBER_ADDRESS.replace('&note->value', '&note'), 'func')
