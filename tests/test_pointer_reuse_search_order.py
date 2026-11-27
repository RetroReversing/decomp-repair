from decomprepair.pointer_pair_repairs import reuse

SOURCE = '''void f(int mode) {
    void *a;
    void *b;
    void *c;
    void *__repair_phase;
    void *result;
    if (mode == 1) {
        a = get_a();
        use(a);
    } else if (mode == 2) {
        b = get_b();
        use(b);
    } else if (mode == 3) {
        c = get_c();
        use(c);
    } else if (mode == 4) {
        __repair_phase = get_d();
        use(__repair_phase);
    } else {
        result = get_e();
        use(result);
    }
}
'''


def test_phase_pairs_are_offered_in_both_directions():
    children = [text for _, text in reuse(SOURCE, 'f')]
    assert any('result = get_d();' in text and 'result = get_e();' in text for text in children)
    assert any('__repair_phase = get_d();' in text and '__repair_phase = get_e();' in text for text in children)


def test_overlapping_pointer_lifetimes_are_not_merged():
    text = SOURCE.replace('        use(__repair_phase);', '        result = get_e();\n        use(__repair_phase, result);')
    children = [child for _, child in reuse(text, 'f')]
    assert not any('result = get_d();' in child for child in children)
    assert not any('__repair_phase = get_e();' in child for child in children)


def test_local_lane_offers_pointer_reuse():
    from decomprepair import registry

    repair = next(item for item in registry.all() if item.module == 'pointer_local_reuse_lane')
    assert repair.runs_in('local', 'mips')
    children = registry.run(repair.module, source=SOURCE, name='f', header='')
    assert any('result = get_d();' in text for _, text in children)
