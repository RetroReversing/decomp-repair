from decomprepair import registry
from decomprepair.stored_member_readback import FAMILY, UNFENCED, variants

BEST = """void func(void *arg0) {
    s16 sum;
    s32 x;

    x = 1;
    do { *(s8 *)((char *)(arg0) + 0x71) = x;
    sum = (*(u16 *)((char *)(arg0) + 0x3A)) + x; } while (0);
    (*(s16 *)((char *)(arg0) + 0x6A)) = sum;
    if (((*(s32 *)((char *)(arg0) + 0x38)) + 0x20) < (sum & 0xFFFF)) {
        other(arg0);
    }
}
"""


def children(source):
    return variants(source, 'func')


def test_mask_reads_the_member_back_as_unsigned():
    found = [c for f, c in children(BEST) if f == FAMILY]
    assert len(found) == 1
    assert '< ((*(u16 *)((char *)(arg0) + 0x6A)))) {' in found[0]
    assert 'do {' in found[0]


def test_the_read_back_and_the_open_fence_come_as_one_child():
    found = [c for f, c in children(BEST) if f == UNFENCED]
    assert len(found) == 1
    assert 'do {' not in found[0] and 'while (0)' not in found[0]
    assert '(u16 *)((char *)(arg0) + 0x6A)' in found[0]
    assert 'sum & 0xFFFF' not in found[0]


def test_casts_field_macro_and_a_same_typed_local():
    source = """void func(char *p) {
    u8 t;
    s32 a;
    M2C_FIELD(p, u8 *, 4) = t;
    a = (s8) t;
    if (t > 3) {
        a = 0;
    }
}
"""
    found = [c for _, c in children(source)]
    assert any('a = (M2C_FIELD(p, s8 *, 4));' in c and 'if ((M2C_FIELD(p, u8 *, 4)) > 3)' in c for c in found)


def test_nothing_across_a_call_a_store_or_a_wider_member():
    for between in ('other();', '*p = 0;', 't = 2;'):
        source = f"""void func(char *p) {{
    s16 t;
    *(s16 *)(p + 2) = t;
    {between}
    if ((u16) t) {{
        t = 0;
    }}
}}
"""
        assert children(source) == []
    wide = """void func(char *p) {
    s32 t;
    *(s32 *)(p + 4) = t;
    if ((t & 0xFFFF) > 1) {
        t = 0;
    }
}
"""
    assert children(wide) == []


def test_registered():
    assert any(r.module == 'stored_member_readback' for r in registry.declared())
