from decomprepair.arm_call_result_inline import FAMILY, variants

# the shape m2c writes for a game's sprintf in each arm: one variable per arm for what the arms differ in
MERGED = '''void f(s32 flag, u16 *rec)
{
    char buf[64];
    s32 *name;
    u32 id;

    if (flag) {
        name = lookup(rec[20] | 0x9000);
        id = 0xA2;
    } else {
        name = lookup(rec[20] | 0x9000);
        id = 0x16A;
    }
    sprintf(buf, fmt, name, lookup(id));
    show(buf);
}
'''

# arms that already call, each with its own temporary (m2c wrote the call into the arms here)
ARMED = '''void g(s32 flag, u16 *rec)
{
    char buf[64];

    if (flag) {
        s32 *name;

        name = lookup(rec[20] | 0x9000);
        sprintf(buf, fmt, name, lookup(0x16A));
    } else {
        s32 *name;

        name = lookup(rec[20] | 0x9000);
        sprintf(buf, fmt, name, lookup(0xA2));
    }
    show(buf);
}
'''


def made(source, name):
    return [text for family, text in variants(source, name) if family == FAMILY]


def test_the_call_goes_into_each_arm_with_the_lookup_written_into_it():
    texts = made(MERGED, 'f')
    assert len(texts) == 1
    text = texts[0]
    assert 'sprintf(buf, fmt, lookup(rec[20] | 0x9000), lookup(0xA2));' in text
    assert 'sprintf(buf, fmt, lookup(rec[20] | 0x9000), lookup(0x16A));' in text
    assert 'name' not in text and 'u32 id' not in text and 'id = ' not in text
    assert text.count('sprintf(') == 2 and 'show(buf);' in text


def test_arms_that_already_call_just_lose_their_temporary():
    texts = made(ARMED, 'g')
    assert len(texts) == 1
    text = texts[0]
    assert 'sprintf(buf, fmt, lookup(rec[20] | 0x9000), lookup(0x16A));' in text
    assert 'sprintf(buf, fmt, lookup(rec[20] | 0x9000), lookup(0xA2));' in text
    assert 'name' not in text


def test_a_temporary_read_anywhere_else_stays():
    other = ARMED.replace('    show(buf);', '    show(buf);\n    after(name);')
    assert not made(other, 'g')
    # also when one arm's temporary is not passed to the next call alone
    twice = ARMED.replace('sprintf(buf, fmt, name, lookup(0xA2));', 'sprintf(buf, fmt, name, name);')
    assert not made(twice, 'g')


def test_an_earlier_argument_that_calls_keeps_the_order():
    """`sprintf(buf, pick(), name, ...)`: pick() ran after the lookup before, and would run before it now."""
    source = ARMED.replace('sprintf(buf, fmt, name, lookup(0x16A));', 'sprintf(buf, pick(), name, lookup(0x16A));') \
                  .replace('sprintf(buf, fmt, name, lookup(0xA2));', 'sprintf(buf, pick(), name, lookup(0xA2));')
    assert not made(source, 'g')
