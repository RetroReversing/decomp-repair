from decomprepair.switch_selector_phase_reuse import variants

SOURCE = '''void f(int input) {
    s32 status;
    s32 local;
    status = input & 0xF0;
    switch (status) {
    case 1:
        status = helper();
        use(status);
        break;
    case 2:
        local = input & 0xFF;
        use(local);
        break;
    }
}
'''


def test_reuses_case_local_for_selector():
    out = variants(SOURCE, 'f')
    assert len(out) == 1
    assert 'local = input & 0xF0;\n    switch (local)' in out[0][1]
    assert 'status = helper();' in out[0][1]


def test_rejects_live_old_or_uninitialized_replacement():
    assert not variants(SOURCE.replace('        status = helper();', ''), 'f')
    assert not variants(SOURCE.replace('        local = input & 0xFF;', ''), 'f')
    assert not variants(SOURCE.replace('        use(status);', '        use(status); use(local);'), 'f')
    assert not variants(SOURCE, 'f', '#define local hidden')
