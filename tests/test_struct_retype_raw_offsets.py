from decomprepair import registry
from decomprepair.struct_retype_raw_offsets import FAMILY, REPAIR, variants

SOURCE = """extern s32 D_80001234;
void upd(void *arg0, void *other) {
    M2C_FIELD(arg0, s32 *, 0x10) = 3;
    D_80001234 = M2C_FIELD(arg0, f32 *, 0x14);
    M2C_FIELD(arg0, void **, 0x1C) = other;
}
"""


def kids(source=SOURCE):
    return [c for f, c in variants(source, 'upd') if f == FAMILY]


def test_every_access_of_the_pointer_becomes_a_member_of_one_struct():
    child = kids()[0]
    assert 'typedef struct { u8 pad_0[0x10]; s32 f10; f32 f14; u8 pad_18[0x4]; void * f1C; } PtrRec_arg0;' in child
    assert '((PtrRec_arg0 *) arg0)->f10 = 3;' in child
    assert 'D_80001234 = ((PtrRec_arg0 *) arg0)->f14;' in child and 'M2C_FIELD(arg0' not in child


def test_the_record_comes_before_the_function():
    child = kids()[0]
    assert child.index('typedef struct') < child.index('void upd')


def test_an_overlapping_or_unaligned_access_stays_raw_and_the_rest_are_members():
    child = kids(SOURCE.replace('f32 *, 0x14', 'u16 *, 0x12'))[0]
    assert 'typedef struct { u8 pad_0[0x10]; s32 f10; u8 pad_14[0x8]; void * f1C; } PtrRec_arg0;' in child
    assert 'D_80001234 = M2C_FIELD(arg0, u16 *, 0x12);' in child and '((PtrRec_arg0 *) arg0)->f10 = 3;' in child
    child = kids(SOURCE.replace('f32 *, 0x14', 's16 *, 0x11'))[0]
    assert 'M2C_FIELD(arg0, s16 *, 0x11)' in child and '((PtrRec_arg0 *) arg0)->f1C = other;' in child


def test_the_more_used_of_two_overlapping_accesses_is_the_member():
    source = SOURCE.replace('D_80001234 = M2C_FIELD(arg0, f32 *, 0x14);',
                            'D_80001234 = M2C_FIELD(arg0, u16 *, 0x12) + M2C_FIELD(arg0, u16 *, 0x12) + M2C_FIELD(arg0, u16 *, 0x12);')
    child = kids(source)[0]
    assert 'u16 f12;' in child and 'M2C_FIELD(arg0, s32 *, 0x10) = 3;' in child


def test_two_members_must_remain():
    source = SOURCE.replace('f32 *, 0x14', 'u16 *, 0x12').replace('M2C_FIELD(arg0, void **, 0x1C) = other;', '')
    assert not kids(source)


def test_one_offset_alone_or_nothing_to_order_against_is_not_offered():
    assert not kids(SOURCE.replace('M2C_FIELD(arg0, f32 *, 0x14)', '4').replace('M2C_FIELD(arg0, void **, 0x1C) = other;', ''))
    assert not kids(SOURCE.replace('D_80001234 = M2C_FIELD(arg0, f32 *, 0x14);', 'x = M2C_FIELD(arg0, f32 *, 0x14);').replace('M2C_FIELD(arg0, s32 *, 0x10) = 3;', 'y = M2C_FIELD(arg0, s32 *, 0x10);').replace('M2C_FIELD(arg0, void **, 0x1C) = other;', ''))


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}


def test_a_function_pointer_typedef_is_a_four_byte_member():
    source = 'typedef void (*Fn)(void *);\n' + SOURCE.replace('void **, 0x1C', 'Fn *, 0x1C')
    assert 'Fn f1C;' in kids(source)[0]
