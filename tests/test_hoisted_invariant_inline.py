from decomprepair import hoisted_invariant_inline as h

# m2c's names for what the loop pass hoisted: `temp_s1` and `sp14` are `arg1 - 1` and `arg2 >> 1` (a homemade function)
DRAFT = '''void f(s32 *arg0, u32 arg1, u32 arg2, u32 arg3)
{
    u32 temp_s1;
    u32 sp14;
    u32 var_t4;
    u32 var_t5;

    var_t5 = arg3;
    temp_s1 = arg1 - 1;
    sp14 = (u32) arg2 >> 1;
    do {
        var_t4 = var_t5 + 1;
        if (temp_s1 < var_t4) {
            var_t4 = temp_s1;
        }
        *arg0 = var_t4 + sp14;
        var_t5 += 2;
    } while (var_t5 < arg1);
}
'''


def _all(source=DRAFT):
    return [text for _, text in h.variants(source, 'f')]


def test_every_invariant_is_written_where_it_is_read_and_each_one_alone():
    kids = _all()
    both, first, second = kids[0], kids[1], kids[2]
    assert 'temp_s1' not in both and 'sp14' not in both
    assert 'if ((arg1 - 1) < var_t4) {' in both and 'var_t4 = (arg1 - 1);' in both
    assert '*arg0 = var_t4 + ((u32) arg2 >> 1);' in both
    assert 'u32 temp_s1;' not in both and 'sp14 =' not in both
    assert 'temp_s1' not in first and 'sp14 = ' in first
    assert 'sp14' not in second and 'temp_s1 = ' in second


def test_a_local_assigned_twice_stays():
    twice = DRAFT.replace('var_t5 += 2;', 'var_t5 += 2;\n        temp_s1 = 0;')
    assert all('temp_s1 = arg1 - 1;' in k for k in _all(twice))
    assert any('sp14' not in k for k in _all(twice))


def test_a_parameter_the_value_names_must_never_change():
    changed = DRAFT.replace('var_t5 += 2;', 'var_t5 += 2;\n        arg1 -= 1;')
    assert all('temp_s1 = arg1 - 1;' in k for k in _all(changed))


def test_a_value_read_from_memory_or_through_a_call_is_not_an_invariant():
    for value in ('g(arg1)', '*arg0', 'arg0[1]'):
        out = [t for _, t in h.variants(DRAFT.replace('arg1 - 1', value), 'f')]
        assert all(f'temp_s1 = {value};' in t for t in out)


def test_a_local_only_read_after_the_loop_is_left_alone():
    source = DRAFT.replace('    } while (var_t5 < arg1);\n', '    } while (var_t5 < arg1);\n    *arg0 = temp_s1;\n').replace(
        'if (temp_s1 < var_t4) {\n            var_t4 = temp_s1;\n        }', 'var_t4 = var_t4;')
    assert all('temp_s1 = arg1 - 1;' in t for _, t in h.variants(source, 'f'))


def test_the_module_declares_itself_to_the_registry():
    assert h.REPAIR['families'] == ('hoisted_invariant_inline',)
