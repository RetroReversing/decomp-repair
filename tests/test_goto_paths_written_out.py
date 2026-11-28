"""Jumps into other arms' tails, written as the paths they run."""
from decomprepair import goto_paths_written_out as paths
from decomprepair import registry

SOURCE = '''s32 check(s32 which)
{
    s32 ok;

    ok = 1;
    if (which != 0) {
        if (gReady == 1) {
            if (find(0) == 5) {
                if (gFree >= 0x300) {
                    goto block_9;
                }
                goto block_8;
            }
        } else {
            goto block_11;
        }
    } else {
        if (gReady == 1) {
            if (find(1) == 5) {
                if (gFree < 0x100) {
block_8:
                    ok = 0;
                    gOut = 1;
                    goto block_11;
                }
block_9:
                if (gUsed >= 16) {
                    gFull = 1;
                    goto block_11;
                }
            }
        } else {
block_11:
        }
    }
    return ok;
}
'''


def child(source=SOURCE):
    (family, text), = paths.variants(source, 'check')
    assert family == paths.FAMILY
    return text


def squeeze(text):
    return ' '.join(text.split())


def test_each_jump_is_written_as_the_path_it_runs():
    text = squeeze(child())
    assert 'goto' not in text and 'block_' not in text
    assert squeeze('''if (find(0) == 5) {
        if (gFree >= 0x300) { if (gUsed >= 16) { gFull = 1; } } else { ok = 0; gOut = 1; } }''') in text
    assert squeeze('''if (find(1) == 5) {
        if (gFree < 0x100) { ok = 0; gOut = 1; } else if (gUsed >= 16) { gFull = 1; } }''') in text
    assert text.endswith('return ok; }')


def test_what_both_ways_run_stays_after_the_if():
    source = 's32 f(s32 a)\n{\n    if (a == 0) {\n        goto out;\n    }\n    g();\n    h();\nout:\n    return a;\n}\n'
    text = squeeze(child_of(source))
    assert 'if (a == 0) { } else { g(); h(); } return a; }' in text


def test_a_jump_to_another_return_keeps_it_and_drops_the_unreachable_copy():
    source = '''s32 f(s32 a)
{
    if (a != 0) {
        if (a == 1) {
            goto out;
        }
        g();
    }
    h();
    return 0;
out:
    return 1;
}
'''
    text = squeeze(child_of(source))
    assert 'if (a == 1) { return 1; } else { g(); } } h(); return 0; }' in text


def child_of(source):
    (_, text), = paths.variants(source, 'f')
    return text


def test_a_backward_jump_declines():
    source = 's32 f(s32 a)\n{\nloop:\n    a--;\n    if (a != 0) {\n        goto loop;\n    }\n    return a;\n}\n'
    assert paths.variants(source, 'f') == []


def test_a_jump_inside_a_loop_declines():
    source = '''s32 f(s32 a)
{
    while (a != 0) {
        if (a == 3) {
            goto out;
        }
        a--;
    }
out:
    return a;
}
'''
    assert paths.variants(source, 'f') == []


def test_the_family_is_registered():
    assert any(paths.FAMILY in repair.families for repair in registry.declared())
