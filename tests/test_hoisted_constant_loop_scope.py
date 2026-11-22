from decomprepair.hoisted_constant_loop_scope import FAMILY, MARK, variants

SOURCE = '''extern s32 liveCount;
s32 release(s32 id)
{
    char *rec;
    u16 **slot;
    u16 head;
    u32 index;
    s32 seen;
    s32 result;
    index = 0;
    if (liveCount != 0)
    {
        s32 wanted = (u16) id;
        slot = (u16 **) table;
        loop_top:
        rec = (char *) (*slot);
        head = *((u16 *) rec);
        seen = 0;
        if (head != 0xFFFF)
        {
            do
            {
                if (head == wanted)
                {
                    touch(rec);
                }
                if (*((u16 *) (rec + 2)) != 0)
                {
                    seen = 1;
                }
                rec += 0x1C;
                head = *((u16 *) rec);
            }
            while (head != 0xFFFF);
        }
        if (seen)
        {
            result = 1;
            return 1;
        }
        index += 1;
        slot += 3;
        if (index >= ((u32) liveCount))
        {
            goto done;
        }
        goto loop_top;
    }
    done:
    result = 0;
    return result;
}
'''


def offered(source=SOURCE, **kwargs):
    return [text for family, text in variants(source, 'release', **kwargs) if family == FAMILY]


def combination(texts):
    return [t for t in texts if t.count(MARK) == 2 and 'result = liveCount;' in t]


def test_the_loop_that_ends_on_a_literal_is_wrapped_in_one_or_two_scopes():
    texts = offered()
    one = [t for t in texts if t.count('} while (0);') == 1]
    two = [t for t in texts if t.count('} while (0);') == 2 and 'do { do {' in t]
    assert one and two
    assert any(MARK + 'do { do\n' in t for t in one)


def test_the_counter_bump_is_scoped_after_the_global_is_read_into_a_dead_local():
    texts = offered()
    both, = combination(texts)
    assert 'result = liveCount;\n        ' + MARK + 'do { index += 1; slot += 3; } while (0);' in both
    assert 'if (index >= ((u32) result))' in both
    assert both.count('do\n') == 1 and MARK + 'do { do\n' in both


def test_each_part_is_offered_alone_too():
    texts = offered()
    assert any(t.count(MARK) == 1 and 'liveCount;' not in t.split('{', 1)[1] and 'result = liveCount' not in t and 'do { index' not in t for t in texts)
    assert any(t.count(MARK) == 1 and 'do { index += 1; slot += 3; } while (0);' in t and 'result = liveCount' not in t for t in texts)
    assert any(t.count(MARK) == 1 and 'result = liveCount;' in t for t in texts)


def test_a_local_that_is_read_is_not_the_temporary():
    texts = offered(SOURCE.replace('result = 0;\n    return result;', 'result = 0;\n    return seen + result;'))
    assert not combination(texts)
    assert not any('seen = liveCount' in t for t in texts)


def test_a_loop_that_ends_on_zero_or_a_register_is_not_wrapped():
    assert not [t for t in offered(SOURCE.replace('while (head != 0xFFFF);', 'while (head != 0);')) if t.count(MARK) and 'do { do' in t]
    assert not [t for t in offered(SOURCE.replace('while (head != 0xFFFF);', 'while (head != wanted);')) if t.count(MARK) and 'do { do' in t]


def test_a_bump_before_a_local_compare_is_not_offered():
    texts = offered(SOURCE.replace('index >= ((u32) liveCount)', 'index >= ((u32) seen)'))
    assert not any('do { index' in t for t in texts)


def test_a_source_that_was_already_scoped_is_left_alone():
    assert variants(offered()[0], 'release') == []
