from decomprepair.callee_narrow_return import variants

SOURCE = '''s32 spawn(s32, f32);
void f(void)
{
    u16 e;
    u16 e2;

    e = spawn(1, 2.0f);
    if ((u16) (e + 2) >= 2U) {
        e2 = spawn(2, 0.0f);
        g(e2);
    }
}
'''


def test_return_type_follows_the_narrow_locals():
    assert [s for _, s in variants(SOURCE, 'f')] == [SOURCE.replace('s32 spawn', 'u16 spawn')]


def test_a_wider_or_mixed_use_keeps_the_prototype():
    assert variants(SOURCE.replace('u16 e2;', 's16 e2;'), 'f') == []
    assert variants(SOURCE.replace('g(e2);', 'g(spawn(3, 0.0f));'), 'f') == []
