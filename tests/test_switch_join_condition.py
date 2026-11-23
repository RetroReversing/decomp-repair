from decomprepair import switch_join_condition as join

SOURCE = '''void f(s32 kind, s32 a) {
    s32 flag;
    s32 weight;

    switch (kind) {
        case 0:
        case 45:
            weight = 1;
            flag = a & 0xFF;
            if (kind == 45) {
                weight = 2;
            }
            break;
        case 1:
            if (a != 7) {
                a = 1;
            }
            goto join;
        case 25:
            weight = 3;
            flag = a & 0xFF;
            break;
        default:
            join:
            flag = a & 0xFF;
    }

    if (flag != 0) {
        use(weight);
    }
}
'''


def test_the_arms_assignments_labels_and_gotos_become_the_joins_own_test():
    (family, text), = join.variants(SOURCE, 'f')
    assert family == 'switch_join_condition'
    assert 'flag' not in text
    assert 'goto' not in text and 'join:' not in text
    assert 'if ((a & 0xFF) != 0) {' in text
    assert text.count('break;') == 4
    assert 'default:\n            break;' in text
    assert text.count('{') == text.count('}')


def test_a_value_changed_after_an_arms_assignment_or_read_elsewhere_is_left_alone():
    assert not join.variants(SOURCE.replace('weight = 2;', 'a = 2;'), 'f')
    assert not join.variants(SOURCE.replace('use(weight);', 'use(flag);'), 'f')
    assert not join.variants(SOURCE.replace('flag = a & 0xFF;\n            break;', 'flag = a & 0x7F;\n            break;'), 'f')
    assert not join.variants(SOURCE.replace('    if (flag != 0) {', '    g();\n    if (flag != 0) {'), 'f')


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'switch_join_condition' in declared and not registry.problems(declared['switch_join_condition'])
