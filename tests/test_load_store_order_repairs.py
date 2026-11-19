"""A load through a pointer written before the global store ahead of it."""
from decomprepair import load_store_order_repairs as o

SOURCE = '''void f(void *arg0, s32 arg3) {
    D_800E1A30 = arg3;
    D_800E1A68 = 0;
    D_800C7E6C = M2C_FIELD(arg0, u8 *, 0x44);
    g(arg0);
}
'''


def test_the_load_goes_first():
    # An N64 function at 96.2%: exact with the field's load before the store.
    (family, out), = o.variants(SOURCE, 'f')
    assert family == 'load_before_store'
    assert '    D_800C7E6C = M2C_FIELD(arg0, u8 *, 0x44);\n    D_800E1A68 = 0;\n' in out


def test_left_alone_otherwise():
    assert o.variants(SOURCE.replace('M2C_FIELD(arg0, u8 *, 0x44)', 'arg3'), 'f') == []  # no load
    assert o.variants(SOURCE.replace('D_800E1A68 = 0;', 'D_800E1A68 = h();'), 'f') == []  # a call
    assert o.variants(SOURCE.replace('(arg0, u8 *, 0x44)', '(D_800E1A68, u8 *, 0x44)'), 'f') == []  # reads it
