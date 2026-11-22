from decomprepair import halfword_store_repairs as module

SOURCE = '''typedef short s16;
typedef unsigned short u16;
typedef int s32;
void f(f32 *src)
{
    struct { f32 a, b, c; s16 x, y, z; } L;
    s16 r;
    s16 q;
    s32 w;
    r = (s16) (s32) L.a;
    q = (s16) (s32) L.b;
    w = (s32) L.c;
    L.x = r;
    L.y = q;
    L.z = (s16) w;
    call(&L.x, w);
}
'''


def variants():
    return [t for family, t in module.variants(SOURCE, 'f', '', 'mips') if family == module.FAMILY]


def test_stores_into_halfword_members_of_a_local_struct_are_normalized():
    texts = variants()
    assert len(texts) == 4                   # each store alone, then all three
    bundle = texts[-1]
    assert 'L.x = __repair_store_halfword(r);' in bundle
    assert 'L.y = __repair_store_halfword(q);' in bundle
    assert 'L.z = __repair_store_halfword(w);' in bundle
    assert 'static inline short __repair_store_halfword(int x)' in bundle
    assert 'L.z = (s16) w;' in texts[0]


def test_a_volatile_struct_or_an_address_taken_local_is_left_alone():
    assert not module.local_record_sites(SOURCE.replace('s16 x, y, z', 'volatile s16 x, y, z'), 'f', '', 'mips')
    assert not module.local_record_sites(SOURCE.replace('call(&L.x, w);', 'call(&L.x, &w);'), 'f', '', 'mips')[2:]
