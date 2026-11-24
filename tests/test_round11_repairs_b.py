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


CLAMP = '''void f(void *arg0, void *arg1, void *arg2) {
    s32 temp_v1;
    s32 temp_v1_2;
    s32 temp_v1_3;
    s32 temp_v1_4;

    temp_v1 = M2C_FIELD(arg2, s32 *, 0);
    if (temp_v1 < M2C_FIELD(arg0, s32 *, 0)) {
        M2C_FIELD(arg0, s32 *, 0) = temp_v1;
    }
    temp_v1_2 = M2C_FIELD(arg2, s32 *, 4);
    if (temp_v1_2 < M2C_FIELD(arg0, s32 *, 4)) {
        M2C_FIELD(arg0, s32 *, 4) = temp_v1_2;
    }
    temp_v1_3 = M2C_FIELD(arg2, s32 *, 8);
    if (M2C_FIELD(arg0, s32 *, 8) < temp_v1_3) {
        M2C_FIELD(arg0, s32 *, 8) = temp_v1_3;
    }
    temp_v1_4 = M2C_FIELD(arg2, s32 *, 0xC);
    if (M2C_FIELD(arg0, s32 *, 0xC) < temp_v1_4) {
        M2C_FIELD(arg0, s32 *, 0xC) = temp_v1_4;
    }
}
'''


def test_a_clamp_guard_that_stores_its_temporary_is_inlined_and_mirrored_as_a_subset():
    # A six-guard clamp function (KMC GCC 2.7.2): the guards that named the temporary first, mirrored as
    # `a[k] > b[k]`, and the others as they were, was exact (30 -> 0); all or none mirrored is another program.
    out = [text for _, text in compared.variants(CLAMP, 'f')]
    assert len(out) == len(set(out)) <= compared.LIMIT
    assert all('temp_v1' not in text for text in out)
    both = ('if (M2C_FIELD(arg0, s32 *, 0) > M2C_FIELD(arg2, s32 *, 0)) {\n        M2C_FIELD(arg0, s32 *, 0) = M2C_FIELD(arg2, s32 *, 0);')
    tail = 'if (M2C_FIELD(arg0, s32 *, 8) < M2C_FIELD(arg2, s32 *, 8)) {\n        M2C_FIELD(arg0, s32 *, 8) = M2C_FIELD(arg2, s32 *, 8);'
    # the inlined-only child keeps every comparison as written; the mirrored ones do the left-hand guards
    assert any('if (M2C_FIELD(arg2, s32 *, 0) < M2C_FIELD(arg0, s32 *, 0)) {' in t for t in out)
    # every guard that named the temporary first is mirrored, the right-hand ones stay
    assert any(both in t and 'M2C_FIELD(arg0, s32 *, 4) > M2C_FIELD(arg2, s32 *, 4)' in t and tail in t for t in out)
    # the first guard alone, and the first guard left out
    assert any(both in t and 'if (M2C_FIELD(arg2, s32 *, 4) < M2C_FIELD(arg0, s32 *, 4)) {' in t for t in out)
    assert any(both not in t and 'M2C_FIELD(arg0, s32 *, 4) > M2C_FIELD(arg2, s32 *, 4)' in t for t in out)


def test_a_stored_temporary_is_left_alone_when_memory_is_written_before_the_store():
    stale = CLAMP.replace('    if (temp_v1 < M2C_FIELD(arg0, s32 *, 0)) {\n',
                          '    M2C_FIELD(arg2, s32 *, 0) = 5;\n    if (temp_v1 < M2C_FIELD(arg0, s32 *, 0)) {\n')
    assert all('temp_v1 = M2C_FIELD(arg2, s32 *, 0);' in t for _, t in compared.variants(stale, 'f'))  # that one stays
    only_stored = CLAMP.replace('    if (temp_v1 < M2C_FIELD(arg0, s32 *, 0)) {\n        M2C_FIELD(arg0, s32 *, 0) = temp_v1;\n    }\n', '    M2C_FIELD(arg0, s32 *, 0) = temp_v1;\n')
    assert all('temp_v1 =' in t for _, t in compared.variants(only_stored, 'f'))  # no comparison: that one stays


def test_propose_finds_the_clamp_inline():
    from decomprepair.propose import propose
    assert any(p.module == 'compared_load_inline_repairs' for p in propose(CLAMP, 'f').proposals)
