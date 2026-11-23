from decomprepair import unsigned_conversion_repairs as repair

SOURCE = '''void f(void *p, f32 a)
{
    f32 t;
    t = a * 0.5f;
    if (t >= 2.1474836e9f) {
        (*(u16 *)((char *)(p) + 0x26)) = (u16) ((s32) (t - 2.1474836e9f) | 0x80000000);
    } else {
        (*(u16 *)((char *)(p) + 0x26)) = (u16) (s32) t;
    }
    g();
}
'''


def test_a_narrowing_store_through_a_cast_lvalue_is_written_as_the_conversion():
    found = [t for _, t in repair.variants(SOURCE, 'f')]
    assert found
    assert '(*(u16 *)((char *)(p) + 0x26)) = (u16) (u32) t;\n    g();' in found[0]
    assert '2.1474836e9f' not in found[0]


def test_the_arms_may_come_either_way_round():
    swapped = '''void f(void *p, f32 a)
{
    f32 t;
    t = a * 0.5f;
    if (!(t >= 2.1474836e9f)) {
        (*(s16 *)((char *)(p) + 0x26)) = (s16) (s32) t;
    } else {
        (*(s16 *)((char *)(p) + 0x26)) = (s16) ((s32) (t - 2.1474836e9f) | 0x80000000);
    }
}
'''
    assert any('= (s16) (u32) t;' in t for _, t in repair.variants(swapped, 'f'))


def test_two_stores_to_different_places_are_left_alone():
    other = SOURCE.replace('(*(u16 *)((char *)(p) + 0x26)) = (u16) (s32) t;', '(*(u16 *)((char *)(p) + 0x28)) = (u16) (s32) t;')
    assert not [t for _, t in repair.variants(other, 'f') if '(u32) t' in t]
