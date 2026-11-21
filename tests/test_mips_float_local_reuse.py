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


ACCUMULATORS = """\
void f(int control) {
    f32 var_s5;
    f32 var_s6;
    f32 temp_s5_2;
    f32 temp_s6_2;
    var_s5 = var_s6 = 0.0f;
    if (control) {
        temp_s5_2 = first();
        temp_s6_2 = second();
        poll();
        var_s5 = temp_s5_2 + adjust();
        var_s6 = temp_s6_2 + adjust();
    }
    emit(var_s5, var_s6);
}
"""


def accumulator_choices(source):
    return [candidate for family, candidate in repair.variants(source, 'f')
            if family == repair.ACCUMULATOR_FAMILY]


def test_reuses_two_independent_accumulators_together_and_individually():
    joint, x_only, z_only = accumulator_choices(ACCUMULATORS)
    assert 'temp_s5_2' not in joint
    assert 'temp_s6_2' not in joint
    assert 'var_s5 = first();' in joint
    assert 'var_s6 = second();' in joint
    assert 'var_s5 = var_s5 + adjust();' in joint
    assert 'var_s6 = var_s6 + adjust();' in joint
    assert 'temp_s6_2 = second();' in x_only
    assert 'temp_s5_2 = first();' in z_only


def test_preserves_accumulators_with_reads_or_address_escapes():
    for use in ('observe(var_s5);', 'observe(&var_s5);'):
        [candidate] = accumulator_choices(ACCUMULATORS.replace('poll();', use))
        assert 'temp_s5_2 = first();' in candidate
        assert 'var_s6 = second();' in candidate


def test_leaves_control_flow_bypasses_unchanged():
    assert not accumulator_choices(ACCUMULATORS.replace('poll();', 'if (broken()) goto done;')
                                   .replace('    emit(', 'done: emit('))
    [candidate] = accumulator_choices(ACCUMULATORS.replace('var_s5 = temp_s5_2', 'if (test()) var_s5 = temp_s5_2'))
    assert 'temp_s5_2 = first();' in candidate
