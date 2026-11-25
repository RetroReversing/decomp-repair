"""void * locals and parameters that take arithmetic are declared u8 * (void_pointer_arithmetic.py)."""
from decomprepair.void_pointer_arithmetic import externs, rewrite, stores

DRAFT = """M2C_UNK func_80309D58(void *, u32, void *, void *);   /* extern */

s32 func_8032C6E0(void *arg0, void *arg1, M2C_UNK arg2) {
    void *var_v1;
    void *temp_v0;
    void **table;

    temp_v0 = func_80309D58(arg0 + 4, 3, arg0, arg1);
    var_v1 = arg1;
    var_v1 += 8;
    table = &arg1;
    return 0;
}
"""


def test_a_name_that_takes_arithmetic_is_a_byte_pointer():
    out = rewrite(DRAFT, 'func_8032C6E0')
    assert 's32 func_8032C6E0(u8 *arg0, void *arg1, M2C_UNK arg2) {' in out
    assert '    u8 *var_v1;' in out
    assert '    void *temp_v0;' in out  # only assigned and passed on
    assert '    void **table;' in out
    assert 'void *, u32, void *, void *' in out  # the prototypes keep void *


def test_nothing_to_change_is_none():
    assert rewrite('void f(void *a) {\n    g(a);\n}\n', 'f') is None
    assert rewrite(DRAFT, 'other') is None


def test_subscripts_dereferences_and_a_leading_operand_count():
    src = 'void f(void *a, void *b, void *c, void *d) {\n    x = a[1];\n    y = 4 + b;\n    z = *c;\n    w = d == 0;\n}\n'
    out = rewrite(src, 'f')
    assert out.startswith('void f(u8 *a, u8 *b, u8 *c, void *d) {')


def test_an_extern_the_draft_declares_takes_arithmetic():
    src = 'extern void *D_80134C00;\nextern void *D_1;\nvoid f(void) {\n    D_80134C00 += 4;\n    g(D_1);\n}\n'
    out = externs(src, 'f')
    assert 'extern u8 *D_80134C00;' in out and 'extern void *D_1;' in out
    assert externs('extern void *D_1;\nvoid f(void) {\n    g(D_1);\n}\n', 'f') is None


def test_a_store_printed_as_a_call_through_a_cast_is_a_store():
    src = '    ((void (*)()) *(s32 *))((a * 0x150) + &D_1) = *(s32 *)(b + 4) + g((f32) (x));\n    y = 1;\n'
    assert stores(src) == '    *(s32 *)((a * 0x150) + &D_1) = *(s32 *)(b + 4) + g((f32) (x));\n    y = 1;\n'
    assert stores('    x = 1;\n') is None
