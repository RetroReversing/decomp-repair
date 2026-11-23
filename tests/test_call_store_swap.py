from decomprepair.call_store_swap import FAMILY, variants

SOURCE = '''void f(void *arg0, s32 mode)
{
    void *state;
    state = *(void **) ((char *) arg0 + 0x6C);
    switch (mode)
    {
        case 0:
            setup(arg0, 1);
            *(s32 *) ((char *) state + 0xA4) = 0;
            break;
        case 1:
            setup(arg0, 8);
            break;
        case 2:
            only_here(arg0);
            *(s32 *) ((char *) state + 0x10) = 0;
            break;
    }
}
'''


def swapped(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_store_goes_before_a_call_other_arms_make_too():
    texts = swapped()
    assert len(texts) == 1
    assert 'state + 0xA4) = 0;\n            setup(arg0, 1);' in texts[0]
    assert 'only_here(arg0);\n            *(s32 *) ((char *) state + 0x10)' in texts[0], 'a callee with one site stays'


def test_a_store_that_calls_something_stays_after_its_call():
    texts = swapped(SOURCE.replace('state + 0xA4) = 0;', 'state + 0xA4) = pick(arg0);'))
    assert not texts


def test_a_call_followed_by_another_call_is_not_swapped():
    assert not swapped(SOURCE.replace('*(s32 *) ((char *) state + 0xA4) = 0;', 'other(state);'))
