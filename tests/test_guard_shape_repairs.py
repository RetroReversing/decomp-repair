from decomprepair import guard_shape_repairs as shape

EARLY = '''void f(void *a, f32 b) {
    void *t;

    t = *(void **)((s8 *)a + 0x18);
    if (t == NULL) {
        *(s32 *)((s8 *)a + 0x24) = 0x1E8;
        return;
    }
    *(s32 *)((s8 *)a + 0x24) = (s32)(b * *(f32 *)((s8 *)t + 8));
}
'''

LOOP = '''void *g(void *a, s32 k) {
    void *p;

    p = *(void **)((u8 *)a + 0x64);
    if (p == NULL) {
        return NULL;
    }
    do {
        if (*((u8 *)p + 0x32) == k) {
            return p;
        }
        p = *(void **)p;
    } while (p != NULL);
    return NULL;
}
'''


def test_early_return_becomes_else_branch():
    # An agent rewrote m2c's early return as the if/else the original source had.
    (family, out), = shape.variants(EARLY, 'f')
    assert family == 'guard_shape'
    assert '''    if (t != NULL) {
        *(s32 *)((s8 *)a + 0x24) = (s32)(b * *(f32 *)((s8 *)t + 8));
    } else {
        *(s32 *)((s8 *)a + 0x24) = 0x1E8;
    }
}''' in out
    assert 'return' not in out


def test_entry_guard_and_do_while_become_one_while_loop():
    (family, out), = shape.variants(LOOP, 'g')
    assert 'while (p != NULL) {' in out and 'do {' not in out and out.count('return NULL;') == 1


def test_changes_meaning_are_left_alone():
    # a value returned by the guard differs from the one after the loop
    assert not shape.variants(LOOP.replace('return NULL;\n    }\n    do', 'return a;\n    }\n    do'), 'g')
    # the loop test is not the guard's inverse
    assert not shape.variants(LOOP.replace('while (p != NULL)', 'while (k != 0)'), 'g')
    # a second return inside the early arm, a goto into the rest, or a value-returning function
    assert not shape.variants(EARLY.replace('0x1E8;', '0x1E8; if (b) return;'), 'f')
    assert not shape.variants(EARLY.replace('(s32)(b', 'goto x; x: (s32)(b'), 'f')
    assert not shape.variants(EARLY.replace('return;', 'return 1;'), 'f')
    # an if/else already there
    assert not shape.variants(EARLY.replace('    *(s32 *)((s8 *)a + 0x24) = (s32)', '    else *(s32 *)((s8 *)a + 0x24) = (s32)'), 'f')


def test_ternary_in_the_rest_is_not_mistaken_for_a_label():
    assert shape.variants(EARLY.replace('(s32)(b', 'b ? 1 : (s32)(b'), 'f')


GUARDED = '''s32 func_80018318(void *arg0) {
    if (arg0 != NULL) {
        return func_80018364(*(s32 *)((s8 *)arg0 + 0x18), *(u16 *)((s8 *)arg0 + 0x1C), func_80018030(*(u16 *)((s8 *)arg0 + 0x1E)) & 0xFFFF);
    }
    return 0;
}
'''


def test_two_returns_become_one_exit_through_a_local():
    # An N64 game built with gcc 2.7.2 -O2: `j` over the zero arm with an empty delay slot, the zero arm laid out
    # last, is one return through a local; two returns put the zero in the delay slot instead.
    outs = [out for _, out in shape.variants(GUARDED, 'func_80018318') if 'return ret;' in out]
    assert len(outs) == 2
    first, flipped = outs
    assert '''s32 func_80018318(void *arg0) {
    s32 ret;
    if (arg0 != NULL) {
        ret = func_80018364(''' in first
    assert '''    } else {
        ret = 0;
    }
    return ret;
}''' in first
    assert '''    if (arg0 == NULL) {
        ret = 0;
    } else {
        ret = func_80018364(''' in flipped
    assert all(out.count('return') == 1 for out in outs)


def test_single_exit_keeps_the_rest_and_the_arm_statements():
    source = '''u8 *g(u8 *p, s32 n) {
    s32 i;

    if (p == NULL) {
        n = 0;
        return NULL;
    }
    i = n + 1;
    p[i] = 2;
    return p + i;
}
'''
    out = next(out for _, out in shape.variants(source, 'g') if 'return ret;' in out)
    assert '''u8 *g(u8 *p, s32 n) {
    u8 *ret;
    s32 i;''' in out
    assert '''    if (p == NULL) {
        n = 0;
        ret = NULL;
    } else {
        i = n + 1;
        p[i] = 2;
        ret = p + i;
    }
    return ret;''' in out


def test_single_exit_left_alone_where_it_would_change_meaning():
    def none(source, name='func_80018318'):
        return not any('return ret' in out for _, out in shape.variants(source, name))
    assert none(GUARDED.replace('s32 func_80018318', 'void func_80018318').replace('return 0;', 'return;'))
    # another return in the rest, a goto, an else already there
    assert none(GUARDED.replace('    return 0;\n', '    if (arg0) return 1;\n    return 0;\n'))
    assert none(GUARDED.replace('    return 0;\n', '    goto x;\nx:\n    return 0;\n'))
    assert none(GUARDED.replace('    }\n    return 0;', '    } else {\n        return 0;\n    }'))


def test_single_exit_local_does_not_clash():
    out = next(out for _, out in shape.variants(GUARDED.replace('(void *arg0)', '(void *ret)').replace('arg0', 'ret'),
                                                'func_80018318') if 'return ret2;' in out)
    assert 's32 ret2;' in out
