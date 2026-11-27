from decomprepair import float_cfg_local_reuse as repair

SOURCE = '''void f(int mode) {
    f32 a;
    f32 sp10;
    a = get();
    consume(a);
    if (mode) { sp10 = get(); } else { sp10 = get(); }
    consume(sp10);
}
'''


def test_reuses_disjoint_float_locals():
    out = repair.variants(SOURCE, 'f')
    assert len(out) == 1
    assert 'f32 a;' not in out[0][1]
    assert 'sp10 = get();\n    consume(sp10);' in out[0][1]


def test_rejects_overlapping_lives_and_escaped_or_volatile_float():
    assert not repair.variants(SOURCE.replace('consume(sp10);', 'consume(sp10, a);'), 'f')
    assert not repair.variants(SOURCE.replace('consume(a);', 'consume(&a);'), 'f')
    assert not repair.variants(SOURCE, 'f', 'typedef volatile float f32;')


def test_rejects_shadows_and_member_names():
    assert not repair.variants(SOURCE.replace('    consume(a);', '    { int a; consume(a); }\n    consume(a);'), 'f')
    assert not repair.variants(SOURCE.replace('    consume(a);', '    consume(obj. a, a);'), 'f')


def test_never_removes_code_after_a_declaration():
    source = SOURCE.replace('    f32 a;\n', '    f32 a; side_effect();\n')
    assert not repair.variants(source, 'f')
