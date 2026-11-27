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


def test_assigned_stack_parameters_are_copied_after_the_clears():
    source = '''void walk(Ball *b, f32 x, f32 y, f32 z, f32 vx, f32 vy, f32 vz) {
    u8 flags = 0;
    u8 count = 0;
    u8 r;
    f32 px, *py;
    while (step(b, x, y, z, vx, vy, vz)) {
        vx = b->x - x;
        vy = b->y - y;
        vz -= z;
        flags |= b->f1;
        count++;
    }
    put(flags, count);
}
'''
    [(family, child)] = [kid for kid in loop_params_entry_copy.variants(source, 'walk')
                         if kid[0] == loop_params_entry_copy.STACK]
    assert 'f32 vx_in, f32 vy_in, f32 vz_in)' in child
    assert child.index('f32 px, *py;') < child.index('f32 vx;') < child.index('vx = vx_in;') < child.index('while')
    assert child.index('u8 count = 0;') < child.index('vx = vx_in;')


def test_constant_sets_stay_ahead_and_read_only_stack_parameters_are_left():
    source = '''void f(s32 a, s32 b, s32 c, s32 d, s32 e, s32 g) {
    s32 n;
    n = 0;
    while (n < g) {
        e += n++;
        use(e);
    }
}
'''
    [(_, child)] = [kid for kid in loop_params_entry_copy.variants(source, 'f') if kid[0] == loop_params_entry_copy.STACK]
    assert child.index('s32 e;') < child.index('n = 0;') < child.index('e = e_in;')
    assert 'g_in' not in child
