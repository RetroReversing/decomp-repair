"""m2c_field_record_view: m2c's M2C_FIELD accesses as record members."""
from decomprepair import m2c_field_record_view as s

SOURCE = '''#ifndef M2C_DEFINES
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
#endif
extern void *D_80001000;

void handler(void *arg0) {
    M2C_FIELD(arg0, s32 *, 0x88) = 1;
    M2C_FIELD(arg0, f32 *, 0x10) = M2C_FIELD(D_80001000, f32 *, 4);
    M2C_FIELD(arg0, void **, 0x14) = D_80001000;
}
'''


def test_every_pointer_becomes_a_record_and_each_alone():
    children = [source for _, source in s.variants(SOURCE, 'handler')]
    every = children[0]
    assert 'M2C_FIELD(arg0' not in every and 'M2C_FIELD(D_80001000' not in every
    assert '(((Rec_handler_arg0 *) arg0)->m88) = 1;' in every
    assert 'char pad0[0x10];' in every and 'void *m14;' in every and 'char pad18[0x70];' in every
    assert every.index('} Rec_handler_arg0;') < every.index('void handler(')
    assert '#define M2C_FIELD(expr, type_ptr, offset)' in every  # the macro itself stays
    assert len(children) == 3
    assert 'M2C_FIELD(D_80001000' in children[1] and 'M2C_FIELD(arg0' not in children[1]


def test_a_pointer_read_two_ways_at_one_offset_stays_as_it_is():
    source = 'void f(void *a) {\n    M2C_FIELD(a, s32 *, 4) = M2C_FIELD(a, f32 *, 4);\n}\n'
    assert s.variants(source, 'f') == []


def test_overlapping_or_misaligned_members_are_refused():
    assert s.variants('void f(void *a) {\n    M2C_FIELD(a, s32 *, 0) = M2C_FIELD(a, s16 *, 2);\n}\n', 'f') == []
    assert s.variants('void f(void *a) {\n    M2C_FIELD(a, s32 *, 2) = 0;\n}\n', 'f') == []


def test_nothing_without_the_macro_or_the_function():
    assert s.variants('void f(void) {\n}\n', 'f') == []
    assert s.variants(SOURCE, 'other') == []
