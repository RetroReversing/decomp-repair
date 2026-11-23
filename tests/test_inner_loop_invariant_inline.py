"""inner_loop_invariant_inline: a value of the outer loop's counters that only the inner loop reads, written at its uses."""
from decomprepair import inner_loop_invariant_inline as i
from decomprepair import registry

DRAFT = '''extern f64 D_800D2EF0;
void f(f32 *out, u32 arg0, u32 arg1, s32 arg2)
{
    f32 temp_ft1;
    u32 temp_t9;
    u32 var_t4;
    u32 var_t6;
    s32 var_t7;

    var_t6 = 0;
    var_t7 = arg2;
    do {
        var_t4 = 0;
        temp_ft1 = (f32) ((f64) (f32) (s32) var_t6 + D_800D2EF0);
        temp_t9 = var_t7 + (arg0 - var_t6);
        do {
            if (temp_t9 < arg1) {
                out[var_t4] = temp_ft1 * 32.0f;
            }
            var_t4 += 1;
        } while (var_t4 < arg0);
        var_t6 += 1;
        var_t7 += arg1;
    } while (var_t6 < arg0);
}
'''


def test_the_two_values_come_back_to_the_inner_loop_in_each_form_and_every_mix():
    out = i.variants(DRAFT, 'f')
    assert {family for family, _ in out} == {'inner_loop_invariant_inline'}
    assert len(out) == 8  # all inline, all sunk, the two mixes, and each local alone in each form
    inline = next(c for _, c in out if 'temp_ft1' not in c and 'temp_t9' not in c)
    assert 'if ((var_t7 + (arg0 - var_t6)) < arg1)' in inline
    assert 'out[var_t4] = ((f32) ((f64) (f32) (s32) var_t6 + D_800D2EF0)) * 32.0f;' in inline
    # the mix the 315-instruction builder needed: the float assigned at the top of the loop, the integer written at its use
    mix = next(c for _, c in out if 'temp_ft1 = (f32)' in c and c.count('temp_ft1 = ') == 1 and 'temp_t9' not in c)
    assert 'do {\n            if' not in mix and 'do { temp_ft1 = (f32) ((f64) (f32) (s32) var_t6 + D_800D2EF0);' in mix
    assert mix.index('do { temp_ft1') > mix.index('var_t4 = 0;')
    sunk = [c for _, c in out if 'temp_ft1' in c and 'temp_t9' in c]
    assert any('do { temp_t9 = var_t7 + (arg0 - var_t6);' in c for c in sunk)


def test_an_operand_the_inner_loop_steps_or_a_read_outside_the_loop_refuses_that_local():
    stepped = DRAFT.replace('var_t4 += 1;\n', 'var_t4 += 1;\n            var_t6 += 1;\n')
    assert i.variants(stepped, 'f') == []
    outside = DRAFT.replace('var_t6 += 1;\n        var_t7', 'out[9] = temp_t9;\n        var_t6 += 1;\n        var_t7')
    children = [child for _, child in i.variants(outside, 'f')]
    assert len(children) == 2  # only the float: written at its uses, or assigned at the top of the loop
    assert all('temp_t9 = var_t7 + (arg0 - var_t6);' in child for child in children)
    assert any('temp_ft1' not in child for child in children)


def test_a_value_with_a_call_or_that_is_set_twice_is_left_alone():
    called = DRAFT.replace('temp_t9 = var_t7 + (arg0 - var_t6);', 'temp_t9 = g(var_t7);')
    children = [child for _, child in i.variants(called, 'f')]
    assert children and all('temp_t9 = g(var_t7);' in child for child in children)
    twice = DRAFT.replace('var_t6 += 1;\n        var_t7', 'temp_t9 = 3;\n        var_t6 += 1;\n        var_t7')
    children = [child for _, child in i.variants(twice, 'f')]
    assert children and all('temp_t9 = var_t7' in child for child in children)


def test_the_module_declares_itself_to_the_registry():
    assert any(r.module == 'inner_loop_invariant_inline' for r in registry.declared())
