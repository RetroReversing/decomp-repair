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


GUARDED_LIFETIMES = """\
void f(int control) {
    f32 var_fs3;
    f32 temp_fs3;
    var_fs3 = first();
    if (control) goto send_first;
    task();
send_first:
    send(var_fs3);
    temp_fs3 = second();
    if (control) goto send_second;
    task();
send_second:
    send(temp_fs3);
}
"""


def test_reuses_float_when_every_jump_to_a_use_follows_its_initializer():
    [(family, candidate)] = repair.variants(GUARDED_LIFETIMES, 'f')
    assert family == repair.FAMILY
    assert 'temp_fs3' not in candidate
    assert 'var_fs3 = second();' in candidate
    assert candidate.count('send(var_fs3);') == 2


def test_goto_from_before_initializer_prevents_reuse():
    outer_entry = GUARDED_LIFETIMES.replace('    temp_fs3 = second();',
                                            '    if (skip()) goto send_second;\n    temp_fs3 = second();')
    inline_label = outer_entry.replace('    task();\nsend_second:', '    task(); send_second:')
    assert not repair.variants(outer_entry, 'f')
    assert not repair.variants(inline_label, 'f')


def test_switch_dispatch_inside_lifetime_prevents_reuse():
    switch_entry = GUARDED_LIFETIMES.replace('    temp_fs3 = second();',
                                             '    switch (control) {\n    temp_fs3 = second();')
    switch_entry = switch_entry.replace('send_second:', 'case 0: send_second:').replace(
        '    send(temp_fs3);', '    send(temp_fs3);\n    }')
    assert not repair.variants(switch_entry, 'f')


ACROSS_CALL = '''
void match(char *obj, char *output, int mode) {
    f32 temp_fs1;
    f32 temp_fs4;
    f32 result;
    if (mode) {
        temp_fs1 = read();
        send(temp_fs1);
    } else {
        temp_fs4 = *((f32 *) (obj + 0x3C)) - (*((f32 *) (output + 0x34)) * 1024.0f);
        result = read_again(mode);
        send(temp_fs4 + result);
        send(temp_fs4);
    }
}
'''


def _across_call_assembly(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


CALL_ROWS = [
    'lwc1 $f2, 0x34($s1)',
    'mul.s $f2, $f2, $f0',
    'lwc1 $f0, 0x3c($s2)',
    'jal read_again',
    'sub.s $f28, $f0, $f2',
]


def across_call_choices(source, rows=CALL_ROWS):
    return [text for family, text in repair.variants(source, 'match', _across_call_assembly(rows))
            if family == repair.ACROSS_CALL_FAMILY]


def test_reuses_disjoint_float_names_to_recover_target_saved_register():
    [candidate] = across_call_choices(ACROSS_CALL)
    assert 'f32 temp_fs4;' not in candidate
    assert 'temp_fs1 = *((f32 *) (obj + 0x3C))' in candidate
    assert 'send(temp_fs1 + result);' in candidate


def test_requires_target_loads_and_saved_difference_in_the_call_delay_slot():
    for index, replacement in ((0, 'lwc1 $f2, 0x38($s1)'),
                               (4, 'sub.s $f0, $f0, $f2'), (3, 'jal other')):
        rows = CALL_ROWS[:index] + [replacement] + CALL_ROWS[index+1:]
        assert not across_call_choices(ACROSS_CALL, rows)


def test_skips_an_escaped_or_overlapping_source_float():
    assert not across_call_choices(ACROSS_CALL.replace('send(temp_fs4);', 'send(temp_fs4 + temp_fs1);'))
    assert not across_call_choices(ACROSS_CALL.replace('send(temp_fs1);', 'hold(&temp_fs1);'))
