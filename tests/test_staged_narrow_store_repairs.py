from decomprepair.staged_narrow_store_repairs import FAMILY, variants

SOURCE = '''void f(void)
{
    struct { f32 a, b, c; s16 x, y, z; } L;
    other(&L);
    L.x = (s16) (s32) L.a;
    L.y = (s16) (s32) L.b;
    keep = 1;
    L.z = (s16) (s32) L.c;
    call(&L.x);
}
'''


def staged(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_run_of_narrowing_stores_goes_through_narrow_locals():
    texts = staged()
    whole = texts[0]
    assert '    s16 __repair_narrow_0;\n    s16 __repair_narrow_1;\n    struct' in whole
    assert '    __repair_narrow_0 = (s16) (s32) L.a;\n    L.x = __repair_narrow_0;\n    __repair_narrow_1 = (s16) (s32) L.b;\n    L.y = __repair_narrow_1;' in whole
    assert 'L.z = (s16) (s32) L.c;' in whole


def test_the_first_and_the_last_store_of_a_run_alone_are_offered_too():
    texts = staged()
    assert any('L.x = __repair_narrow_0;' in t and 'L.y = (s16) (s32) L.b;' in t for t in texts)
    assert any('L.y = __repair_narrow_0;' in t and 'L.x = (s16) (s32) L.a;' in t for t in texts)
    assert any('L.z = __repair_narrow_0;' in t for t in texts)


def test_a_store_into_a_local_is_not_staged():
    assert not staged('void f(void)\n{\n    s16 v;\n    v = (s16) other();\n    keep(v);\n}\n')
