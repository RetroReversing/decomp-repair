"""`M2C_FIELD(p, T *, K)` is a memory access: families that refuse calls must not refuse a raw m2c draft."""
import pytest

from decomprepair import (
    deref_compound_store,
    paired_store_chain,
    readback_store_barrier,
    reload_temp_inline,
    staged_sum_scope,
    statement_group_orders,
)

SOURCES = [
    (statement_group_orders, """void f(void *arg0) {
    s32 a;
    s32 b;

    a = M2C_FIELD(arg0, s32 *, 0);
    b = M2C_FIELD(arg0, s32 *, 4);
}
"""),
    (readback_store_barrier, """void f(void *arg0, s32 arg1) {
    M2C_FIELD(arg0, s32 *, 0) = arg1;
    M2C_FIELD(arg0, s32 *, 4) = M2C_FIELD(arg0, s32 *, 0x10);
    gTotal = M2C_FIELD(arg0, s32 *, 4) + 1;
}
"""),
    (paired_store_chain, """void f(void *arg0, s32 arg1) {
    M2C_FIELD(arg0, s32 *, 0) = arg1;
    M2C_FIELD(arg0, s32 *, 4) = arg1;
}
"""),
    (deref_compound_store, """void f(void *arg0, s32 arg1) {
    M2C_FIELD(arg0, s32 *, 4) = M2C_FIELD(arg0, s32 *, 4) + arg1;
}
"""),
    (reload_temp_inline, """void f(void *arg0) {
    s32 temp;

    temp = M2C_FIELD(arg0, s32 *, 0x34);
    gTotal = temp + 1;
}
"""),
]


@pytest.mark.parametrize('module, source', SOURCES, ids=[module.__name__.split('.')[-1] for module, _ in SOURCES])
def test_a_field_macro_is_not_a_call(module, source):
    assert module.variants(source, 'f')


@pytest.mark.parametrize('module', [statement_group_orders, readback_store_barrier, paired_store_chain,
                                    deref_compound_store, reload_temp_inline, staged_sum_scope])
def test_a_real_call_beside_a_field_macro_is_still_a_call(module):
    pattern = getattr(module, '_CALL', None) or module.CALL
    assert pattern.search('x = get(M2C_FIELD(p, s32 *, 4));')
    assert not pattern.search('x = M2C_FIELD(p, s32 *, 4) + M2C_BITWISE(f32, y);')
