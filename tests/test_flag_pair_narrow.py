from decomprepair.flag_pair_narrow import FAMILY, variants

SOURCE = '''void f(void *p, s32 sel)
{
    long flag;
    int temp;
    flag = 0;
    if (check(p))
    {
        flag = 1;
    }
    temp = flag & (sel >> 31);
    flag = temp;
    if ((temp << 0x18) != 0)
    {
        flag = 0;
        if (more(p))
        {
            flag = more(p) != 0;
        }
    }
    use(p, flag);
}
'''


def narrowed(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_flag_and_the_temporary_that_masks_it_are_both_typed_char():
    texts = narrowed()
    assert len(texts) == 2
    assert '    char flag;\n    char temp;\n' in texts[0]
    assert '    s8 flag;\n    s8 temp;\n' in texts[1]
    assert all('flag = temp;' in text for text in texts)


def test_a_pair_already_byte_sized_or_without_the_copy_back_is_left_alone():
    assert not narrowed(SOURCE.replace('long flag;', 'char flag;').replace('int temp;', 'char temp;'))
    assert not narrowed(SOURCE.replace('    flag = temp;\n', '    other = temp;\n'))
    assert not narrowed(SOURCE.replace('use(p, flag);', 'use(p, &flag);'))
