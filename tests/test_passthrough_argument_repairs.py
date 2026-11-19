"""The caller's own parameter passed on to a callee m2c gave one argument too few."""
from decomprepair import passthrough_argument_repairs as p

SOURCE = '''s32 g();
s32 h(s32, s32);

s32 f(s32 arg0, void *arg1, s32 arg2) {
    if (D != NULL) {
        g(arg0, D, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24));
        return 1;
    }
    h(arg0, arg2);
    return 0;
}
'''


def test_each_parameter_at_its_own_position():
    # An N64 function at 95%: the game called g(arg0, D, arg2, ...), its $a2 untouched; exact so.
    calls = [text[text.index('        g('):text.index(';', text.index('        g('))] for _, text in p.variants(SOURCE, 'f')]
    assert '        g(arg0, D, arg2, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24))' in calls
    assert '        g(arg0, arg1, D, M2C_FIELD(arg1, s32 *, 0xC), M2C_FIELD(arg1, s32 *, 0x24))' in calls


def test_only_unprototyped_callees():
    assert all('h(arg0, arg2);' in text for _, text in p.variants(SOURCE, 'f'))
    assert p.variants(SOURCE.replace('s32 g();', 's32 g(s32, void *, s32, s32);'), 'f') == []
