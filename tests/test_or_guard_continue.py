"""A loop body ending in `if (A || B) { ... }`, written as the two tests that skip it."""
import re

from decomprepair.or_guard_continue import FAMILY, variants

CODE = '''extern unsigned char gPause;
extern void work(int);
void run(int n)
{
    int j;
    for (j = 0; j < n; j++) {
        work(j);
        if (gPause == 0 || j != 1) {
            work(j + 1);
            work(j + 2);
        }
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_or_test_becomes_two_skips():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert 'work(j); if (gPause != 0) { if (j == 1) { continue; } } { work(j + 1); work(j + 2); } } }' in text
    assert '||' not in text


def test_other_shapes_are_left_alone():
    assert variants(CODE.replace('gPause == 0 || j != 1', 'gPause == 0 && j != 1'), 'run') == []
    assert variants(CODE.replace('gPause == 0 || j != 1', 'work(j) || j != 1'), 'run') == []
    assert variants(CODE.replace('gPause == 0 || j != 1', 'gPause == 0 || j != 1 || j > 3'), 'run') == []
    assert variants(CODE.replace('work(j + 2);', 'continue;'), 'run') == []
    assert variants(CODE.replace('        }\n    }\n}', '        }\n        work(9);\n    }\n}'), 'run') == []
    assert variants(CODE, 'missing') == []


def test_an_or_continue_is_split_into_two_continues():
    code = CODE.replace('        if (gPause == 0 || j != 1) {\n            work(j + 1);\n            work(j + 2);\n        }\n',
                        '        if (gPause == 0 || j != 1) {\n            continue;\n        }\n        work(j + 1);\n')
    children = [squash(text) for _, text in variants(code, 'run')]
    assert any('if (gPause == 0) { continue; } if (j != 1) { continue; } work(j + 1);' in text for text in children)
    assert all('||' not in text for text in children[:1])
    assert not any('if (gPause == 0) { continue; }' in squash(text) for _, text in
                   variants(code.replace('gPause == 0 || j != 1', 'work(j) || j != 1'), 'run'))
