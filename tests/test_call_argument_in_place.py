from decomprepair.call_argument_in_place import DROP, UPDATE, variants

LOADER = '''void f(s32 arg0) {
    u32 limit;
    u32 head;
    limit = D_8006DE88;
    head = D_80083AB0;
    if (arg0 != 0) {
        load(head, ALIGN16(limit));
        finish(0, 0);
    }
}
'''

RANKS = '''void f(s32 rank) {
    if (rank != 0) {
        sprintf(&D_8007F9AC, D_80008854, rank);
    } else {
        sprintf(&D_8007F9AC, D_80008864, rank);
    }
}
'''


def children(source, family):
    return [text for found, text in variants(source, 'f') if found == family]


def test_the_argument_is_updated_in_the_local_before_the_call():
    child, = children(LOADER, UPDATE)
    assert '        limit = ALIGN16(limit);\n        load(head, limit);\n' in child


def test_a_local_read_later_or_in_a_loop_is_left():
    assert not children(LOADER.replace('finish(0, 0)', 'finish(limit, 0)'), UPDATE)
    looped = LOADER.replace('if (arg0 != 0) {', 'while (arg0 != 0) {')
    assert not children(looped, UPDATE)
    assert not children(LOADER.replace('ALIGN16(limit)', 'measure(limit)'), UPDATE)


def test_the_argument_known_to_be_zero_is_dropped():
    child, = children(RANKS, DROP)
    assert 'sprintf(&D_8007F9AC, D_80008854, rank);' in child
    assert 'sprintf(&D_8007F9AC, D_80008864);' in child


def test_an_arm_that_assigns_the_variable_keeps_it():
    assert not children(RANKS.replace('    } else {\n', '    } else {\n        rank = 2;\n'), DROP)
    flipped = '''void f(s32 n) {
    if (n == 0) {
        say(fmt, n);
    }
}
'''
    assert 'say(fmt);' in children(flipped, DROP)[0]
