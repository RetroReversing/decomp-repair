"""scaled_copy_in_place: `T = X * K;` where nothing reads X afterwards, written back into X."""
from decomprepair import registry
from decomprepair import scaled_copy_in_place as s

LOOP = '''void f(s32 *out, u32 arg0, u32 arg1)
{
    s32 var_a0;
    s32 temp_a0_3;
    u32 var_t4;
    s32 var_t5;

    var_t4 = 0;
    var_t5 = 3;
    do {
        var_a0 = var_t5 + arg0;
        if (var_a0 >= 0x141) {
            var_a0 = 0x140;
        }
        temp_a0_3 = var_a0 * 4;
        out[var_t4] = temp_a0_3 * 2;
        var_t4 += 1;
        var_t5 += arg1;
    } while (var_t4 < 8);
}
'''


def test_the_scaled_copy_is_written_back_into_the_local_and_its_later_reads_follow():
    [(family, child)] = s.variants(LOOP, 'f')
    assert family == 'scaled_copy_in_place'
    assert 'var_a0 = var_a0 * 4;' in child and 'out[var_t4] = var_a0 * 2;' in child
    assert 'temp_a0_3' not in child


def test_a_local_read_after_the_statement_is_left_alone():
    source = LOOP.replace('out[var_t4] = temp_a0_3 * 2;', 'out[var_t4] = temp_a0_3 * 2 + var_a0;')
    assert s.variants(source, 'f') == []


def test_a_loop_that_reads_the_local_before_assigning_it_is_left_alone():
    source = LOOP.replace('        var_a0 = var_t5 + arg0;\n', '        out[1] = var_a0;\n        var_a0 = var_t5 + arg0;\n')
    assert s.variants(source, 'f') == []


def test_a_shift_by_a_constant_counts_and_a_parameter_does_not():
    source = LOOP.replace('temp_a0_3 = var_a0 * 4;', 'temp_a0_3 = var_a0 << 2;')
    [(_, child)] = s.variants(source, 'f')
    assert 'var_a0 = var_a0 << 2;' in child
    parameter = LOOP.replace('temp_a0_3 = var_a0 * 4;', 'temp_a0_3 = arg0 * 4;')
    assert s.variants(parameter, 'f') == []


def test_the_module_declares_itself_to_the_registry():
    assert any(r.module == 'scaled_copy_in_place' for r in registry.declared())
