"""Round eleven: a store carried out of both arms, and loads held for comparisons."""
from decomprepair import carried_store_arms_repairs as carried
from decomprepair import compared_load_inline_repairs as compared

CARRIED = '''void f(void *p) {
    s32 var_v0;

    if (g() > 0) {
        h(-1);
        var_v0 = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x14;
    } else {
        k();
        var_v0 = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x1C;
    }
    M2C_FIELD(p, s32 *, 0x28) = var_v0;
    m(&D);
}
'''


def test_the_store_goes_into_each_arm():
    # An N64 function at 99.3%: the shared value lived in a saved register; exact with a store per arm.
    (family, out), = carried.variants(CARRIED, 'f')
    assert family == 'carried_store_arms'
    assert 'var_v0' not in out
    assert '        M2C_FIELD(p, s32 *, 0x28) = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x14;\n    } else {' in out
    assert '        M2C_FIELD(p, s32 *, 0x28) = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x1C;\n    }\n    m(&D);' in out


def test_carried_left_alone_when_the_variable_is_read_elsewhere():
    assert carried.variants(CARRIED.replace('    m(&D);', '    m(var_v0);'), 'f') == []
    assert carried.variants(CARRIED.replace('        h(-1);\n', '        h(var_v0);\n'), 'f') == []
    no_else = CARRIED.replace('''    } else {
        k();
        var_v0 = (M2C_FIELD(p, s32 *, 0x28) & ~0xFC) | 0x1C;
    }''', '    }')
    assert carried.variants(no_else, 'f') == []


COMPARED = '''s32 f(void *arg0, void *arg1, void *arg2) {
    f32 temp_fv1;
    s32 var_v0;

    var_v0 = 0;
    temp_fv1 = M2C_FIELD(arg0, f32 *, 0xC);
    var_v0 = 1;
    if ((temp_fv1 < M2C_FIELD(arg1, f32 *, 4)) && (temp_fv1 < M2C_FIELD(arg2, f32 *, 4))) {
        var_v0 = 0;
    }
    return var_v0;
}
'''


def test_the_load_is_written_into_each_comparison_both_ways():
    # An N64 bounding-box test at 99.5%: inlined 99.7%, inlined with the other operand first exact.
    (_, inlined), (family, flipped) = compared.variants(COMPARED, 'f')
    assert family == 'compared_load_inline'
    assert 'temp_fv1' not in inlined and 'temp_fv1' not in flipped
    assert '(M2C_FIELD(arg0, f32 *, 0xC) < M2C_FIELD(arg1, f32 *, 4))' in inlined
    assert '(M2C_FIELD(arg1, f32 *, 4) > M2C_FIELD(arg0, f32 *, 0xC))' in flipped
    assert '(M2C_FIELD(arg2, f32 *, 4) > M2C_FIELD(arg0, f32 *, 0xC))' in flipped


def test_compared_left_alone_otherwise():
    assert compared.variants(COMPARED.replace('    var_v0 = 1;\n', '    g();\n'), 'f') == []  # a call between
    assert compared.variants(COMPARED.replace('return var_v0;', 'return temp_fv1;'), 'f') == []  # not only compared
    stored = COMPARED.replace('    var_v0 = 1;\n', '    M2C_FIELD(arg0, f32 *, 0xC) = 0.0f;\n')
    assert compared.variants(stored, 'f') == []  # a store between


def test_propose_finds_both():
    from decomprepair.propose import propose
    assert any(p.module == 'carried_store_arms_repairs' for p in propose(CARRIED, 'f').proposals)
    assert any(p.module == 'compared_load_inline_repairs' for p in propose(COMPARED, 'f').proposals)
