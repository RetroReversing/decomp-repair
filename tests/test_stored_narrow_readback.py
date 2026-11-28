from decomprepair import registry
from decomprepair.stored_narrow_readback import FAMILY, variants

SOURCE = '''extern M2C_UNK D_view;
extern s16 D_a;
extern s16 D_b;

void setup(s16 arg0) {
    s16 temp_v0;
    s32 temp_a0;

    temp_v0 = arg0 * 2;
    M2C_FIELD(&D_view, s16 *, 0) = temp_v0;
    M2C_FIELD(&D_view, s16 *, 8) = temp_v0;
    temp_a0 = (s32) (arg0 << 0x11) >> 0x12;
    D_a = (s16) temp_a0;
    D_b = (s16) temp_a0;
}
'''

MATCHED = '''extern M2C_UNK D_view;
extern s16 D_a;
extern s16 D_b;

void setup(s16 arg0) {

    M2C_FIELD(&D_view, s16 *, 0) = arg0 * 2;
    M2C_FIELD(&D_view, s16 *, 8) = arg0 * 2;
    D_a = M2C_FIELD(&D_view, s16 *, 0) >> 2;
    D_b = M2C_FIELD(&D_view, s16 *, 0) >> 2;
}
'''


def test_combined_child_reads_the_halfword_back():
    children = variants(SOURCE, 'setup')
    assert children[0] == (FAMILY, MATCHED)
    assert len(children) == 4


def test_unsigned_global_is_read_signed():
    source = '''extern u16 D_w;
extern s16 D_a;
void setup(s32 x) {
    D_w = x << 1;
    D_a = (s32) (x << 0x11) >> 0x11;
}
'''
    assert 'D_a = (s16) D_w >> 1;' in variants(source, 'setup')[0][1]


def test_refuses_when_the_halfword_may_have_changed():
    for between in ('touch();', '*p = 0;', 'M2C_FIELD(&D_view, s16 *, 0) = 1;', 'arg0 = 3;', 'D_view = 0;',
                    'x = M2C_FIELD(&D_view, s16 *, 0) = 4;', '(*D_callback)(1);', 'arg0++;'):
        source = SOURCE.replace('    temp_a0 =', f'    {between}\n    temp_a0 =')
        assert variants(source, 'setup') == [], between


def test_declares_itself():
    assert any(FAMILY in entry.families for entry in registry.declared())
