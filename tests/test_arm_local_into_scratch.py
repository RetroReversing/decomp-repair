from decomprepair.arm_local_into_scratch import FAMILY, variants

SOURCE = '''void f(u8 *rec, void *obj)
{
    s32 scratch;
    long kind;

    scratch = rec[0x80];
    use(scratch);
    kind = table[rec[1]];
    if (kind != rec[0x81]) {
        g(obj + (kind * 2));
        h(obj + (scratch * 2));
    }
    done();
}
'''


def made(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_load_goes_into_the_scratch_the_arm_reads():
    texts = made()
    assert len(texts) == 1
    text = texts[0]
    assert text.index('scratch = kind;') > text.index('if (kind != rec[0x81]) {')
    assert 'g(obj + (scratch * 2));' in text and 'h(obj + (scratch * 2));' in text
    assert 'kind * 2' not in text and 'if (kind != rec[0x81])' in text


def test_a_scratch_read_after_the_arm_or_not_read_in_it_stays():
    after = SOURCE.replace('    done();', '    done(scratch);')
    assert not made(after)
    unread = SOURCE.replace('        h(obj + (scratch * 2));\n', '        h(obj);\n')
    assert not made(unread)


def test_a_loop_or_another_width_stays():
    assert not made(SOURCE.replace('    done();', '    while (x) { done(); }'))
    assert not made(SOURCE.replace('    s32 scratch;', '    u8 scratch;'))
