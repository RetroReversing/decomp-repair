from decomprepair.call_arg_stage_before_guard import FAMILY, variants

SOURCE = '''void f(void *arg0, s32 flags)
{
    s32 flag;
    flag = 1;
    if (flags & 0x40)
    {
        if (!(a(arg0) > b(arg0)))
        {
            flag = 0;
        }
        first(arg0 + 0x24, 1, flag);
    }
    else
    {
        if (!(c(arg0) > d(arg0)))
        {
            flag = 0;
        }
        second(arg0 + 0x24, 1, flag);
    }
}
'''


def staged(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_address_argument_is_computed_before_the_guard_that_sets_the_last_argument():
    texts = staged()
    assert len(texts) == 3, 'each call, and both together'
    one = next(t for t in texts if 'second(arg0 + 0x24' in t)
    assert '        arg0_arg = arg0 + 0x24;\n        if (!(a(arg0) > b(arg0)))' in one
    assert 'first(arg0_arg, 1, flag);' in one and '    void *arg0_arg;\n' in one
    both = next(t for t in texts if 'second(arg0_arg' in t and 'first(arg0_arg' in t)
    assert both.count('void *arg0_arg;') == 1


def test_a_guard_with_more_than_one_statement_or_a_call_without_an_address_is_left_alone():
    assert not staged(SOURCE.replace('flag = 0;', 'flag = 0;\n            other(arg0);'))
    assert not staged(SOURCE.replace('first(arg0 + 0x24, 1, flag);', 'first(arg0, 1, flag);').replace('second(arg0 + 0x24, 1, flag);', 'second(arg0, 1, flag);'))
