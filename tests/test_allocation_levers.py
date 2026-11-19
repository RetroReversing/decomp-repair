"""Rewrites that only change which registers gcc 2.7.2 picks: operand order, statement order, written-out compound
assignments, declaration order; and record tables addressed by subscript, whose `addu` puts the index first."""
from decomprepair import allocation_lever_repairs as a
from decomprepair import row_subscript_repairs as r

ROW = '''void f(s32 arg0) {
    s32 temp_a0;
    u8 *temp_v1;

    temp_a0 = arg0 * 0x68;
    temp_v1 = (char *)((D_800E41DC)); temp_v1 += (s32)((temp_a0));
    if (*temp_v1 != 0) {
        *temp_v1 = 0;
        M2C_FIELD((temp_a0 + D_800E41DC), s8 *, 0x61) = 1;
    }
}
'''


def test_a_scaled_index_becomes_a_row_subscript():
    # An N64 function at 99.7%, off by `addu`'s operand order: exact as rows of bytes, with nothing else to infer.
    (family, out), = r.variants(ROW, 'f')
    assert family == 'row_subscript'
    assert 'if (((u8 (*)[0x68]) D_800E41DC)[arg0][0x0] != 0) {' in out
    assert '((s8 (*)[0x68]) D_800E41DC)[arg0][0x61] = 1;' in out
    assert 'temp_a0' not in out and 'temp_v1' not in out


def test_a_pointer_used_otherwise_is_kept():
    kept = ROW.replace('        *temp_v1 = 0;\n', '        g(temp_v1);\n')
    out = [t for _, t in r.variants(kept, 'f')]
    assert all('temp_v1 = ' in t for t in out)
    assert any('((s8 (*)[0x68]) D_800E41DC)[arg0][0x61] = 1;' in t for t in out)


def test_wider_fields_index_their_own_rows():
    source = 'void f(s32 i) {\n    s32 t;\n\n    t = i * 0x10;\n    M2C_FIELD((D + t), s32 *, 8) = 1;\n}\n'
    (_, out), = r.variants(source, 'f')
    assert '((s32 (*)[0x4]) D)[i][0x2] = 1;' in out


LEVER = '''void f(void) {
    u32 x;
    u32 y;

    x = A + B;
    C = x;
    D += (x >> 0x1F) + x;
}
'''


def test_each_lever_is_offered_alone():
    out = [t for _, t in a.variants(LEVER, 'f')]
    assert any('x = B + A;' in t for t in out)
    assert any('D += x + (x >> 0x1F);' in t for t in out)
    assert any('D = D + ((x >> 0x1F) + x);' in t for t in out)
    assert any('    D += (x >> 0x1F) + x;\n    C = x;' in t for t in out)
    assert any(t.index('u32 y;') < t.index('u32 x;') for t in out)
    # x is written by the first statement and read by the second: they don't swap
    assert not any('    C = x;\n    x = A + B;' in t for t in out)


def test_left_alone_without_a_body():
    assert a.variants('int f(void);\n', 'f') == []
    assert r.variants('void f(void) {\n    g();\n}\n', 'f') == []
