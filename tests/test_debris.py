"""What the permuter's bugs left in saved C, taken out."""
from decomprepair import debris

SOURCE = '''void f(void) {
    if (g()) {
        register D_80102ED4 = 0;
    }
    (*(s32 *)((char *)((unsigned short)D_80109698) + 0xFC)) = 1;
    (*(s32 *)(((unsigned)char *)(D_80109698) + 0x100)) = 2;
    v = (s32)w;
}
'''


def test_each_kind_goes():
    out = debris.clean(SOURCE)
    assert '        D_80102ED4 = 0;' in out
    assert '(*(s32 *)((char *)(D_80109698) + 0xFC)) = 1;' in out
    assert '(*(s32 *)((char *)(D_80109698) + 0x100)) = 2;' in out
    assert 'v = (s32)w;' in out  # an ordinary cast stays


def test_nothing_to_take_out():
    assert debris.clean('void f(void) {\n    register s32 v = 0;\n    p = (u8 *)(q) + 1;\n}\n') is None
    assert debris.clean(None) is None
