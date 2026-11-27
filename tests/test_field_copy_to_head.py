"""One field copied from another record, written first in its run of stores."""
from decomprepair import registry
from decomprepair.field_copy_to_head import FAMILY, REPAIR, variants

SOURCE = """void f(void *arg0) {
    void *o;

    o = spawn();
    if (o != NULL) {
        M2C_FIELD(o, s8 *, 0x78) = 1;
        M2C_FIELD(o, s8 *, 0x74) = 1;
        M2C_FIELD(o, s8 *, 0x73) = 0x5A;
        M2C_FIELD(o, s8 *, 0x72) = 0x5A;
        M2C_FIELD(o, s8 *, 0x71) = 0x5A;
        M2C_FIELD(o, s32 *, 0x34) = (s32) M2C_FIELD(arg0, s32 *, 0x34);
        M2C_FIELD(o, u16 *, 0) = (u16) M2C_FIELD(arg0, u16 *, 0);
    }
}
"""


def kids(source=SOURCE):
    return [child for _, child in variants(source, 'f')]


def test_the_copy_goes_to_the_head_of_the_run():
    assert any('if (o != NULL) {\n        M2C_FIELD(o, s32 *, 0x34) = (s32) M2C_FIELD(arg0, s32 *, 0x34);\n'
               '        M2C_FIELD(o, s8 *, 0x78) = 1;' in child and 'M2C_FIELD(o, s8 *, 0x71) = 0x5A;\n'
               '        M2C_FIELD(o, u16 *, 0)' in child for child in kids())


def test_not_past_a_store_to_the_same_cell():
    blocked = SOURCE.replace('M2C_FIELD(o, s8 *, 0x78) = 1;', 'M2C_FIELD(o, s32 *, 0x34) = 0;')
    assert not any('{\n        M2C_FIELD(o, s32 *, 0x34) = (s32)' in child for child in kids(blocked))


def test_a_copy_within_reach_of_the_head_is_statement_slides():
    near = SOURCE.replace('        M2C_FIELD(o, s8 *, 0x73) = 0x5A;\n        M2C_FIELD(o, s8 *, 0x72) = 0x5A;\n', '')
    assert not any('{\n        M2C_FIELD(o, s32 *, 0x34)' in child for child in kids(near))


def test_declared():
    assert REPAIR['families'] == (FAMILY,)
    assert registry.problems(registry.get('field_copy_to_head')) == []
