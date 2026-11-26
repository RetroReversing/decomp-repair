from decomprepair import else_if_guard_thread as thread

SOURCE = """extern signed char P[];
extern signed char G;
extern signed char H;
int f(void)
{
    int r;
    int g;
    r = 0;
    g = G;
    if (H != 5) {
        r = 1;
    } else if (P[0] == g && P[1] == 2) {
        r = 2;
    } else if (P[0] == G && P[1] == 3) {
        r = 3;
    } else if (P[0] == 4) {
        r = 4;
    } else {
        r = 5;
    }
    return r;
}
"""


def test_arms_sharing_a_test_are_nested_under_it():
    (family, text), *rest = thread.variants(SOURCE, 'f')
    assert family == 'else_if_guard_thread' and not rest
    assert 'if (P[0] == g) { if (P[1] == 2) {' in text
    assert 'if (P[0] == G && P[1] == 3) {' in text
    assert text.count('goto chain_done;') == 2
    assert text.index('chain_done:;') > text.index('r = 5;')


def test_a_different_second_test_is_left_alone():
    assert thread.variants(SOURCE.replace('P[0] == G &&', 'P[0] == H &&'), 'f') == []


def test_a_stored_global_is_not_an_alias():
    assert thread.variants(SOURCE.replace('r = 0;', 'r = 0; G = 1;'), 'f') == []


def test_a_call_in_a_later_test_is_left_alone():
    assert thread.variants(SOURCE.replace('P[1] == 3', 'h() == 3'), 'f') == []
