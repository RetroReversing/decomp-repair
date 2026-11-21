from decomprepair import mips_float_local_reuse as repair

SOURCE = """\
void f(int selector) {
    f32 var_fs3;
    f32 temp_fs3;
    f32 temp_fs3_2;
    switch (selector) {
    case 0:
        var_fs3 = read();
        send(var_fs3);
        break;
    case 1:
        temp_fs3 = read();
        send(temp_fs3);
        break;
    case 2:
        temp_fs3_2 = read();
        send(temp_fs3_2);
        break;
    }
}
"""


def test_reuses_disjoint_register_named_locals_across_switch_cases():
    (family, all_reused), (_, keep_one) = repair.variants(SOURCE, 'f')
    assert family == repair.FAMILY
    assert all_reused.count('send(var_fs3);') == 3
    assert all_reused.count('f32 ') == 1
    assert keep_one.count('send(var_fs3);') == 2
    assert 'send(temp_fs3);' in keep_one


def test_skips_overlapping_values_and_unconditional_scope_exits():
    overlap = SOURCE.replace('send(temp_fs3);', 'send(temp_fs3 + var_fs3);')
    for _, candidate in repair.variants(overlap, 'f'):
        assert 'send(temp_fs3 + var_fs3);' in candidate
    escapes = SOURCE.replace('send(temp_fs3);', 'out = &temp_fs3;')
    for _, candidate in repair.variants(escapes, 'f'):
        assert 'out = &temp_fs3;' in candidate


def test_leaves_conditional_and_label_entered_lifetimes_separate():
    conditions = SOURCE.replace('temp_fs3 = read();', 'if (selector) temp_fs3 = read();')
    labels = SOURCE.replace('send(temp_fs3);', 'bypass: send(temp_fs3);')
    for source in (conditions, labels):
        assert repair.variants(source, 'f')
        assert all('send(temp_fs3);' in candidate for _, candidate in repair.variants(source, 'f'))
