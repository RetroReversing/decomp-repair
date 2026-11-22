from decomprepair.goto_tail_order_repairs import FAMILY, variants

SOURCE = '''void f(void *p, s32 which)
{
    void *state;
    s32 value;
    switch (which)
    {
        case 3:
            call_a(p);
            state = *(void **)((char *)p + 0xA8);
            value = 4;
            goto done;
        case 8:
            call_b(p);
            state = *(void **)((char *)p + 0xA8);
            value = 4;
            goto done;
        default:
            break;
        done:
            *(s16 *)((char *)state + 0x7A) = value;
    }
}
'''


def test_second_arm_writes_the_pair_in_the_other_order():
    fixed = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert fixed
    first = fixed[0]
    assert first.index('value = 4;') < first.index('state = ', first.index('call_b'))
    assert first.index('state = ', first.index('call_a')) < first.index('value = 4;', first.index('call_a'))
    assert all(text != SOURCE for text in fixed)


def test_dependent_or_call_pairs_are_left_alone():
    dependent = SOURCE.replace('value = 4;', 'value = (s32)state;')
    assert variants(dependent, 'f') == []
    calls = SOURCE.replace('value = 4;', 'value = get();')
    assert variants(calls, 'f') == []


def test_single_arm_is_not_a_set():
    one = SOURCE.replace('''        case 8:
            call_b(p);
            state = *(void **)((char *)p + 0xA8);
            value = 4;
            goto done;
''', '')
    assert variants(one, 'f') == []
