from decomprepair import equality_ladder_chain, registry

TREE = '''extern int gStep;
extern int gPage;

void pick(int kind) {
    int mode;

    mode = 1;
    if (kind == 1) {
        gPage = kind;
        gStep = 0;
        return;
    }
    if (kind != 2) {
        if (kind == 3) {
            /* Duplicate return node */
            gPage = kind;
            gStep = kind;
            return;
        }
        mode = 7;
        if (kind != 4) {
            if (kind == 5) {
                goto block_9;
            }
        } else {
            gPage = kind;
            gStep = kind;
        }
    } else {
block_9:
        gPage = kind;
        gStep = mode;
    }
}
'''


def children(source, name='pick'):
    return [text for _, text in equality_ladder_chain.variants(source, name)]


def test_tree_becomes_a_chain_with_the_reaching_numbers():
    written, kept = children(TREE)
    assert written.split('void pick(int kind) {\n')[1] == '''    if (kind == 1) {
        gPage = 1;
        gStep = 0;
    } else if (kind == 2) {
        gPage = 2;
        gStep = 1;
    } else if (kind == 3) {
        gPage = 3;
        gStep = 3;
    } else if (kind == 4) {
        gPage = 4;
        gStep = 4;
    } else if (kind == 5) {
        gPage = 5;
        gStep = 7;
    }
}
'''
    assert 'gPage = kind;' in kept and 'gStep = 7;' in kept and 'mode' not in kept and 'goto' not in kept


def test_what_runs_when_no_number_matches_is_the_final_else():
    source = '''int f(int x) {
    if (x != 1) {
        if (x == 2) { return 20; }
        if (x != 3) { return -1; }
        return 30;
    }
    return 10;
}
'''
    text = children(source, 'f')[0]
    assert 'if (x == 1) {\n        return 10;' in text
    assert '} else if (x == 3) {\n        return 30;' in text
    assert '} else {\n        return -1;' in text


def test_casts_stay_and_negative_locals_are_bracketed():
    source = '''void f(int x) {
    int v;
    v = -2;
    if (x == 1) { a = (u8) x; b = c-v; }
    if (x == 2) { a = v; }
    if (x == 3) { a = 0; }
}
'''
    text = children(source, 'f')[0]
    assert 'a = (u8) 1;' in text and 'b = c-(-2);' in text and 'a = (-2);' in text


def test_declines_what_it_cannot_run():
    ladder = 'if (x == 1) { a = 1; } else if (x == 2) { a = 2; } else if (x == 3) { %s }'
    assert children('void f(int x) {\n    %s\n}\n' % (ladder % 'x = 4;'), 'f') == []
    assert children('void f(int x) {\n    %s\n}\n' % (ladder % 'for (;;) { }'), 'f') == []
    assert children('void f(int x) {\n    %s\n}\n' % (ladder % 'g(&x);'), 'f') == []
    assert children('void f(void) {\n    %s\n}\n' % (ladder % 'a = 3;'), 'f') == []
    assert children('void f(int x) {\n    if (x == 1) { a = 1; }\n    if (x == 2) { a = 2; }\n}\n', 'f') == []
    backward = 'void f(int x) {\nagain:\n    if (x == 1) { a = 1; }\n    if (x == 2) { a = 2; }\n    if (x == 3) { goto again; }\n}\n'
    assert children(backward, 'f') == []


def test_a_narrow_local_that_would_convert_its_number_is_left():
    source = '''void f(int x) {
    u8 v;
    v = 511;
    if (x == 1) { a = v; }
    if (x == 2) { a = 2; }
    if (x == 3) { a = 3; }
}
'''
    for text in children(source, 'f'):
        assert 'a = v;' in text and 'v = 511;' in text


def test_declared():
    assert any(r.module.endswith('equality_ladder_chain') for r in registry.declared())
