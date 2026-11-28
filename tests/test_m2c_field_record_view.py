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


GLOBAL = '''extern s32 D_80000FF8;
extern M2C_UNK D_80001000;

void setup(s32 arg0) {
    M2C_FIELD(&D_80001000, s8 *, 0xD) = 0;
    D_80000FF8 = arg0;
    M2C_FIELD(&D_80001000, s32 *, 0) = arg0;
    M2C_FIELD(&D_80001000, u32 *, 8) = 0x100 - arg0;
}
'''


def test_a_global_read_through_its_address_is_declared_as_a_record():
    (family, child), = s.variants(GLOBAL, 'setup')
    assert 'M2C_FIELD(' not in child and 'extern M2C_UNK D_80001000;' not in child
    assert 'extern Rec_setup_D_80001000 D_80001000;' in child
    assert child.index('} Rec_setup_D_80001000;') < child.index('extern Rec_setup_D_80001000 D_80001000;')
    assert child.index('extern Rec_setup_D_80001000 D_80001000;') < child.index('void setup(')
    assert 'D_80001000.mD = 0;' in child and 'D_80001000.m0 = arg0;' in child
    assert 'D_80001000.m8 = 0x100 - arg0;' in child and 'extern s32 D_80000FF8;' in child


def test_a_global_used_bare_is_the_member_at_offset_zero():
    source = ('extern s32 D_80001000;\nvoid f(void) {\n    D_80001000 = M2C_FIELD(&D_80001000, s32 *, 4);\n'
              '    g((s8 *)&D_80001000 + 4, &D_80001000);\n}\n')
    (_, child), = s.variants(source, 'f')
    assert 'D_80001000.m0 = D_80001000.m4;' in child
    assert 'g((s8 *)&D_80001000 + 4, &D_80001000);' in child


def test_a_global_whose_uses_are_not_understood_is_refused():
    access = '    M2C_FIELD(&D_80001000, s32 *, 4) = 0;\n'
    declared = 'extern s32 D_80001000;\n'
    stepped = declared + 'void f(void) {\n' + access + '    g(&D_80001000 + 1);\n}\n'
    assert s.variants(stepped, 'f') == []
    array = 'extern s32 D_80001000[];\nvoid f(void) {\n' + access + '}\n'
    assert s.variants(array, 'f') == []
    assert s.variants('void f(void) {\n' + access + '}\n', 'f') == []
    named = declared + 'void f(void) {\n' + access + '}\n'
    assert s.variants(named, 'f', header='extern s32 D_80001000;\n') == []
    narrow = 'extern s16 D_80001000;\nvoid f(void) {\n' + access + '    D_80001000 = 1;\n'
    assert s.variants(narrow + '    M2C_FIELD(&D_80001000, s32 *, 0) = 2;\n}\n', 'f') == []
