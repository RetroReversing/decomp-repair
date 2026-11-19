"""Equal constant returns written once, the others jumping to it."""
from decomprepair import shared_return_repairs as r

SOURCE = '''s32 f(s32 a) {
    if (a) {
        g(1);
        return 1;
    }
    h(0);
    return 1;
}
'''


def test_the_first_return_jumps_to_the_last():
    texts = [t for _, t in r.variants(SOURCE, 'f')]
    assert any('goto __shared_return_1;' in t and t.count('return 1;') == 1
               and t.index('goto __shared_return_1;') < t.index('__shared_return_1:') for t in texts)


def test_a_lone_return_is_left_alone():
    assert r.variants('s32 f(s32 a) {\n    return 1;\n}\n', 'f') == []
