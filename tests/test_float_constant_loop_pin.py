from decomprepair import float_constant_loop_pin as pin

SOURCE = """\
s32 hit(f32 *, s32);
s32 sweep(s32 a, s32 b, f32 best)
{
    f32 out;
    s32 i;
    s32 found = -1;
    for (i = 0; i < a; i++) {
        if (hit(&out, i) && out >= 0.0f && out < best) {
            best = out;
            found = i;
        }
    }
    for (i = 0; i < b; i++) {
        if (hit(&out, i) && out >= 0.0f && out < best) {
            best = out;
            found = i;
        }
    }
    return found;
}
"""


def test_every_compare_with_the_repeated_constant_goes_through_one_local():
    family, text = pin.variants(SOURCE, 'sweep')[0]
    assert family == 'float_constant_loop_pin'
    assert text.count('(__repair_pin_0 = 0.0f)') == 2
    assert 'out >= (__repair_pin_0 = 0.0f)' in text
    # one uninitialised local at the top: its set and its uses are in different blocks, which loop.c won't move
    assert text.index('f32 __repair_pin_0;') < text.index('for (i = 0; i < a')
    assert '__repair_pin_0 = 0.0f;' not in text.split('f32 out;')[0]


def test_the_initialised_form_is_offered_second():
    variants = pin.variants(SOURCE, 'sweep')
    assert 'f32 __repair_pin_0 = 0.0f;' in variants[1][1]


def test_a_single_occurrence_only_gets_the_initialised_form():
    source = SOURCE.replace('out >= 0.0f && ', '', 1)
    variants = pin.variants(source, 'sweep')
    assert len(variants) == 1
    assert 'f32 __repair_pin_0 = 0.0f;' in variants[0][1]


def test_stores_and_straight_line_code_are_left_alone():
    store = """\
void clear(f32 *p, s32 n)
{
    s32 i;
    for (i = 0; i < n; i++) {
        p[i] = 0.0f;
    }
}
"""
    assert pin.variants(store, 'clear') == []
    straight = """\
s32 above(f32 x, f32 y)
{
    if (x >= 0.0f && y >= 0.0f) {
        return 1;
    }
    return 0;
}
"""
    assert pin.variants(straight, 'above') == []


def test_distinct_values_and_doubles_get_their_own_local():
    source = """\
s32 f(f32 *p, f64 *q, s32 n)
{
    s32 i, k = 0;
    for (i = 0; i < n; i++) {
        if (p[i] > 1.0f) { k++; }
        if (p[i] > 1.0f) { k++; }
        if (q[i] < 0.5) { k++; }
        if (q[i] < 0.5) { k++; }
    }
    return k;
}
"""
    first = pin.variants(source, 'f')[0][1]
    assert 'f32 __repair_pin_0;' in first and 'f64 __repair_pin_1;' in first
    assert '(__repair_pin_0 = 1.0f)' in first and '(__repair_pin_1 = 0.5)' in first
    assert len(pin.variants(source, 'f')) >= 3  # all pinned, all initialised, each value alone


def test_asm_without_a_float_constant_load_declines():
    assert pin.variants(SOURCE, 'sweep', asm='lw $v0, 0($a0)\njr $ra\nnop') == []
    assert pin.variants(SOURCE, 'sweep', asm='mtc1 $zero, $f0\nc.le.s $f0, $f2')


def test_a_second_run_does_not_pin_a_pinned_source():
    text = pin.variants(SOURCE, 'sweep')[0][1]
    assert pin.variants(text, 'sweep') == []


STEP = """\
f32 hit(void *, f32);
f32 search(f32 *pos, f32 best, s32 n)
{
    f32 t;
    f32 ret;
    ret = best;
    for (t = 0.0f; t < (f32)n + 1.0; t += 0.005f) {
        if (hit(pos, t) <= best) {
            ret = t;
        }
    }
    return ret;
}
"""


def test_a_loops_step_is_pinned_through_a_compound_assignment():
    variants = pin.variants(STEP, 'search')
    texts = [text for family, text in variants]
    alone = [text for text in texts if 't += (__repair_pin_0 = 0.005f)' in text and '1.0)' not in text.split('{')[1]]
    assert alone, 'the step alone, beside the bound literal that is left as it was'
    assert 'f32 __repair_pin_0 = 0.005f;' in alone[0]
    assert 't < (f32)n + 1.0;' in alone[0]


def test_compound_assignment_outside_a_loop_is_left_alone():
    straight = """\
f32 bump(f32 x)
{
    x += 0.005f;
    return x;
}
"""
    assert pin.variants(straight, 'bump') == []
