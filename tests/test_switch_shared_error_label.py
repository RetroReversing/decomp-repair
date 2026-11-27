from decomprepair.switch_shared_error_label import variants

SOURCE = '''void f(int type, int status, int i) {
    if (type != 1) {
        if (status == 2) { notify(); return; }
    fail:
        do { do { errors[i] = 2; } while (0); } while (0);
        bad++;
    } else {
        switch (status) {
        case 0: work(); break;
        case 3: do { goto fail; } while (0);
        case 2: notify(); return;
        }
    }
    finish();
}
'''


def test_moves_the_shared_tail_and_retains_early_return():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    result = children[0][1]
    assert 'if (status == 2) { notify(); return; }' in result
    assert 'goto fail;' in result
    assert result.index('case 3:') < result.index('fail:') < result.index('case 2:')
    assert 'bad++;\n break;' in result
    assert result.count('errors[i] = 2;') == 1


def test_rejects_extra_jumps_shadowed_names_and_else_tail():
    assert not variants(SOURCE.replace('if (type != 1)', 'if (status) goto fail; if (type != 1)'), 'f')
    assert not variants(SOURCE.replace('case 0: work();', 'case 0: int bad; work();'), 'f')
    assert not variants(SOURCE.replace('case 0: work();', 'case 0: Custom bad; work();'), 'f')
    assert not variants(SOURCE.replace('        }\n    }\n    finish();', '        }\n        extra();\n    }\n    finish();'), 'f')
    assert not variants(SOURCE, 'f', '#define errors other')
