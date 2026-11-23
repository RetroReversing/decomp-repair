from decomprepair.identical_run_goto import FAMILY, variants

SOURCE = '''void f(u8 *rec, s32 state)
{
    switch (state) {
    case 0:
        if (rec[0]) {
            rec[1] = 1;
            rec[2] = 2;
            gFlags[rec[3] + rec[5]] = (u8) (rec[6] + 7);
        }
        break;
    case 1:
        if (rec[4]) {
            rec[1] = 1;
            rec[2] = 2;
            gFlags[rec[3] + rec[5]] = (u8) (rec[6] + 7);
        }
        break;
    }
    done();
}
'''


def made(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_earlier_copy_jumps_into_the_later_one():
    texts = made()
    assert len(texts) == 2
    text = texts[0]
    assert text.count('rec[1] = 1;') == 1 and text.count('gFlags[rec[3] + rec[5]] = (u8) (rec[6] + 7);') == 1
    assert text.index('goto shared_run_1;') < text.index('shared_run_1:') < text.index('rec[1] = 1;')
    assert text.index('shared_run_1:') > text.index('if (rec[4]) {')
    assert 'case 1:' in text and text.count('break;') == 2  # the dead break after the goto is gone


def test_the_later_copy_may_jump_into_the_earlier_one():
    text = made()[1]
    assert text.index('shared_run_1:') < text.index('rec[1] = 1;') < text.index('goto shared_run_1;')
    assert text.index('shared_run_1:') > text.index('if (rec[0]) {')


def test_different_runs_a_short_run_or_other_tails_stay():
    assert not made(SOURCE.replace('rec[2] = 2;\n            gFlags[rec[3] + rec[5]] = (u8) (rec[6] + 7);\n        }\n        break;\n    }',
                                   'rec[2] = 3;\n            gFlags[rec[3] + rec[5]] = (u8) (rec[6] + 7);\n        }\n        break;\n    }'))
    short = SOURCE.replace('            rec[2] = 2;\n', '').replace('            gFlags[rec[3] + rec[5]] = (u8) (rec[6] + 7);\n', '')
    assert not made(short)
    assert not made(SOURCE.replace('        }\n        break;\n    case 1:', '        }\n        done();\n    case 1:'))
    assert not made(SOURCE.replace('rec[1] = 1;', 'u8 t = 1;'))


def test_a_run_with_a_label_or_a_return_stays():
    assert not made(SOURCE.replace('rec[2] = 2;', 'return;'))
    assert not made(SOURCE.replace('rec[2] = 2;', 'again:'))
