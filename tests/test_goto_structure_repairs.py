"""m2c's backward and forward gotos as the loops and elses they came from."""
from decomprepair import goto_structure_repairs as g

DO_WHILE = '''void f(s32 *arg0, s32 arg1) {
    char *var_a1;
    s32 var_v1;

    var_v1 = 0;
    var_a1 = arg0;
loop_2:
    *(s32 *)var_a1 = 0;
    var_v1 += 1;
    var_a1 += 4;
    if (var_v1 < 4) {
        goto loop_2;
    }
    h(arg1);
}
'''

WHILE = '''void f(s32 arg0) {
    char *var_a1;
    u16 var_v1;

    var_v1 = 0;
    var_a1 = &D;
loop_1:
    if (*(s16 *)var_a1 != arg0) {
        var_v1 += 1;
        var_a1 += 2;
        if (var_v1 >= 0x20U) {
            return;
        }
        goto loop_1;
    }
    E = var_v1;
}
'''

ELSE = '''s32 f(s32 arg0) {
    s32 var_v0;

    if (arg0 == 0) {
        var_v0 = 1;
        goto block_3;
    }
    var_v0 = g(arg0);
block_3:
    return var_v0 + 2;
}
'''


def texts(source, family):
    return [t for f, t in g.variants(source, 'f') if f == family]


def test_a_tail_goto_is_a_do_while():
    # gcc 2.7.2 strength-reduces only loops the C writes: an N64 function's loop was off by its layout as a goto
    out = texts(DO_WHILE, 'goto_backward_loop')
    assert any('''    do {
        *(s32 *)var_a1 = 0;
        var_v1 += 1;
        var_a1 += 4;
    } while (var_v1 < 4);
    h(arg1);''' in t for t in out)
    assert all('goto' not in t and 'loop_2' not in t for t in out)


def test_a_guarded_goto_is_a_while_and_a_for():
    out = texts(WHILE, 'goto_backward_loop')
    assert any('''    while (*(s16 *)var_a1 != arg0) {
        var_v1 += 1;
        var_a1 += 2;
        if (var_v1 >= 0x20U) {
            return;
        }
    }
    E = var_v1;''' in t for t in out)
    assert any('if (*(s16 *)var_a1 == arg0) {\n            break;\n        }' in t for t in out)
    assert any('            continue;\n        }\n        break;\n    }' in t for t in out)


def test_a_jump_over_a_block_is_an_else():
    (out,) = texts(ELSE, 'goto_forward_else')
    assert '''    if (arg0 == 0) {
        var_v0 = 1;
    } else {
        var_v0 = g(arg0);
    }
    return var_v0 + 2;''' in out and 'goto' not in out and 'block_3' not in out


def test_left_alone_when_the_meaning_could_change():
    # a goto from outside the region would enter the loop mid-way
    outside = DO_WHILE.replace('    var_v1 = 0;\n', '    var_v1 = 0;\n    if (arg1) {\n        goto loop_2;\n    }\n')
    assert texts(outside, 'goto_backward_loop') == []
    # a break of an enclosing loop would bind to the new one
    wrapped = DO_WHILE.replace('    *(s32 *)var_a1 = 0;\n', '    if (arg1 == 9) {\n        break;\n    }\n    *(s32 *)var_a1 = 0;\n')
    assert texts(wrapped, 'goto_backward_loop') == []
    # a second goto to the label would lose its target
    twice = ELSE.replace('    var_v0 = g(arg0);\n', '    var_v0 = g(arg0);\n    if (var_v0) {\n        goto block_3;\n    }\n')
    assert texts(twice, 'goto_forward_else') == []


def test_nothing_without_gotos():
    assert g.variants('void f(void) {\n    h();\n}\n', 'f') == []


SHARED = '''void f(s32 arg0) {
    s32 var_v0;

    switch (arg0) {
    case 0:
        var_v0 = 0x94;
        if (D != 0) {
            goto block_6;
        }
        break;
    case 16:
        var_v0 = 0xF;
block_6:
        E = var_v0;
        return;
    }
}
'''

ARM = '''void f(void) {
    s32 var_v0;

    if (A != 0) {
        B = 0x640;
        var_v0 = 0x1388;
        goto block_3;
    }
    B = 0x190;
    C = 0xBB8;
    var_v0 = 0xE74;
    if (D == 0x24) {
block_3:
        C = var_v0;
    }
    E = B - 1;
}
'''


def test_a_shared_tail_is_copied_to_its_goto():
    (out,) = texts(SHARED, 'goto_shared_tail')
    assert '''        if (D != 0) {
            E = var_v0;
            return;
        }
        break;
    case 16:
        var_v0 = 0xF;
        E = var_v0;
        return;''' in out and 'goto' not in out


def test_a_tail_that_continues_elsewhere_is_left_alone():
    # without the return, the goto's case falls out of the switch where the label's case does too, but via `break`
    no_return = SHARED.replace('        E = var_v0;\n        return;\n', '        E = var_v0;\n')
    assert texts(no_return, 'goto_shared_tail') == []


def test_a_goto_into_a_later_if_is_an_else():
    (out,) = texts(ARM, 'goto_forward_else')
    assert '''    if (A != 0) {
        B = 0x640;
        var_v0 = 0x1388;
        C = var_v0;
    } else {
        B = 0x190;
        C = 0xBB8;
        var_v0 = 0xE74;
        if (D == 0x24) {
            C = var_v0;
        }
    }
    E = B - 1;''' in out


NESTED_ENTRY = '''void f(s32 *arg0) {
    s32 *held;
    s32 *buf;
    s32 *tmp;

    held = arg0->x;
    if (held != NULL) {
        goto block_3;
    }
    buf = alloc(8, 1);
    if (buf != NULL) {
        held = buf;
        fill(buf);
block_3:
        use(held);
        goto block_9;
    } else {
block_9:
        done();
    }
    end();
}
'''


def test_nested_entry_becomes_else_arm():
    out = dict((f, t) for f, t in g.variants(NESTED_ENTRY, 'f'))
    text = out[g.NESTED_ENTRY_FAMILY]
    assert 'entry_tmp = arg0->x;' in text
    assert 'if (entry_tmp == NULL) {' in text
    assert 'held = entry_tmp;' in text
    assert 'goto block_3' not in text and 'block_3:' not in text
    assert text.index('if (buf == NULL)') < text.index('fill(buf);') < text.index('use(held);') < text.index('block_9:')
    assert 'goto block_9;\n        goto' not in text
    assert 'goto block_9;' in text


def test_nested_entry_needs_a_single_goto_and_a_declared_variable():
    two = NESTED_ENTRY.replace('    buf = alloc', '    if (arg0) { goto block_3; }\n    buf = alloc')
    assert g.NESTED_ENTRY_FAMILY not in [f for f, _ in g.variants(two, 'f')]
    undeclared = NESTED_ENTRY.replace('    s32 *held;\n', '')
    assert g.NESTED_ENTRY_FAMILY not in [f for f, _ in g.variants(undeclared, 'f')]


FOREVER = '''void f(void) {
    a();
loop_4:
    if (D != 0) {
        D();
    }
    goto loop_4;
}
'''


def test_an_unconditional_backward_goto_is_while_one():
    # an unoptimised (-O0) build keeps a jump for every `continue; break;`, so only a bare `while (1)` matched
    out = texts(FOREVER, 'goto_backward_loop')
    assert any('while (1) {' in t and 'goto' not in t and 'continue' not in t and 'break' not in t for t in out)
