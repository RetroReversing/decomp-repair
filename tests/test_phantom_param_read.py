"""phantom_param_read: a parameter's spill slot read as an uninitialised local, written as the parameter.

Shape of a 157-instruction KMC effect spawner: m2c's `sp1E` (read, never assigned) was the spilled `u16` parameter
between two it had copied into `sp16` and `sp26`; reading the parameter lost its register to a neighbour (368 ->
1866), and the neighbour's only statement in a `do { } while (0)` plus the identical-arm guard written once gave 225."""
from decomprepair import phantom_param_read as w

SOURCE = """void use(s32 a, s32 b);

void *run(void *obj, u16 first, u16 second, u16 third, u16 fourth, u16 fifth)
{
    u16 sp16;
    u16 sp1E;
    u16 sp26;
    s32 value;

    sp16 = first;
    sp26 = fifth;
    use(0, 1);
    switch (third)
    {
        case 0:
            value = 1;
            break;
        case 1:
            value = 2;
            break;
    }
    value = second & 0xFFFF;
    *(u16 *)((char *)obj + 6) = sp1E;
    *(u16 *)((char *)obj + 8) = fourth;
    if (third)
    {
        *(s8 *)((char *)obj + 4) = 0;
    }
    else
    {
        *(s8 *)((char *)obj + 4) = 0;
    }
    return obj;
}
"""


def test_the_parameter_between_the_copied_ones_is_read_first():
    found = w.variants(SOURCE, 'run')
    assert found and all(family == w.FAMILY for family, _ in found)
    first = found[0][1]
    assert 'sp1E' not in first and '*(u16 *)((char *)obj + 6) = second;' in first


def test_the_identical_arm_guard_on_the_chosen_parameter_is_written_once():
    source = SOURCE.replace('*(u16 *)((char *)obj + 6) = sp1E;', '*(u16 *)((char *)obj + 6) = sp1E;\n    if (second)\n    {\n        use(1, 1);\n    }\n    else\n    {\n        use(1, 1);\n    }')
    first = w.variants(source, 'run')[0][1]
    assert 'if (second)' not in first and first.count('use(1, 1);') == 1


def test_a_rival_parameter_gets_its_only_statement_in_a_scope():
    texts = [text for _, text in w.variants(SOURCE, 'run')]
    assert any('do { value = second & 0xFFFF; } while (0);' in t or 'do { *(u16 *)((char *)obj + 8) = fourth; } while (0);' in t
               for t in texts)


def test_a_local_that_is_assigned_is_not_a_phantom():
    source = SOURCE.replace('    use(0, 1);\n', '    use(0, 1);\n    sp1E = fifth;\n')
    assert w.variants(source, 'run') == []


def test_a_function_without_a_phantom_has_no_children():
    assert w.variants(SOURCE.replace('sp1E', 'value'), 'run') == []
