"""A global table read in a guarded loop's body, read through a pointer the guard's block sets."""
from decomprepair.guard_loop_table_pointer import FAMILY, variants

SRC = '''typedef struct Vec3i { s32 x; s32 y; s32 z; } Vec3i;
extern Vec3i D_800AA1BC[];
extern s32 D_80107040;

s32 f(Obj *o, Rec *p, s32 *a)
{
    s32 i;
    if (D_80107040 & 0x4000) {
        for (i = 0; i < 4; i++) {
            f32 ex = o->x - (p->x + D_800AA1BC[i].x);
            f32 ez = o->z - (p->z + D_800AA1BC[i].z);
            a[i] = ex * ex + ez * ez;
        }
    }
    return a[0];
}
'''


def kids():
    return [src for fam, src in variants(SRC, 'f') if fam == FAMILY]


def test_the_guard_block_sets_a_pointer_the_loop_reads_through():
    want = SRC.replace('    if (D_80107040 & 0x4000) {\n',
                       '    if (D_80107040 & 0x4000) {\n        Vec3i *tp = D_800AA1BC;\n')
    want = want.replace('D_800AA1BC[i].x', 'tp[i].x').replace('D_800AA1BC[i].z', 'tp[i].z')
    assert kids() == [want]


def test_a_loop_outside_any_guard_and_volatile_sources_are_left_alone():
    plain = SRC.replace('    if (D_80107040 & 0x4000) {\n', '    {\n')
    assert [s for fam, s in variants(plain, 'f') if fam == FAMILY] == []
    assert variants(SRC.replace('s32 i;', 'volatile s32 i;'), 'f') == []
