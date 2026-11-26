from decomprepair import loop_params_entry_copy

SOURCE = '''void draw(s32 *gfx, s32 x, s32 y, s32 dx, u8 alpha, s32 count) {
    s32 cur;
    s32 i;
    cur = x;
    for (i = 0; i < count; i++) {
        plot(gfx, cur, y, alpha);
        cur = dx + cur;
        cur = x;
    }
}
'''


def test_loop_read_parameters_are_copied_together():
    children = [text for family, text in loop_params_entry_copy.variants(SOURCE, 'draw')]
    assert len(children) == 2
    words, widened = children
    assert 's32 * gfx_in' in words and 'x_in' in words and 'y_in' in words and 'dx_in' in words
    assert 'u8 alpha,' in words
    assert 's32 alpha_in' in widened and 'u8 alpha;' in widened and 'alpha = alpha_in;' in widened
    assert 'count_in' not in widened
    assert widened.index('s32 i;') < widened.index('x = x_in;') < widened.index('cur = x;')


def test_nothing_without_a_loop_or_with_a_taken_address():
    assert not loop_params_entry_copy.variants('void f(s32 a, s32 b) { g(a, b); }', 'f')
    taken = SOURCE.replace('plot(gfx, cur, y, alpha);', 'plot(&gfx, cur, &y, alpha); g(&x, &dx);')
    assert not loop_params_entry_copy.variants(taken, 'draw')
