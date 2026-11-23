from decomprepair.member_read_local import FAMILY, variants

SOURCE = '''void f(void *arg0)
{
    struct Scratch
    {
        s32 a[4];
        void *sp44;
        s32 count;
    } scratch;
    scratch.sp44 = NULL;
    fill(arg0, &scratch.count, &scratch.sp44);
    if ((scratch.sp44 != NULL) && ((*((u16 *) (((char *) scratch.sp44) + 0x78))) == 0xB))
    {
        *((s32 *) (((char *) scratch.sp44) + 0x60)) = (*((s32 *) (((char *) scratch.sp44) + 0x60))) | 8;
    }
    if (scratch.count > 0)
    {
        use(scratch.count);
    }
}
'''


def copied(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_pointer_member_read_four_times_in_one_if_is_read_from_a_local():
    texts = copied()
    assert len(texts) == 1
    text = texts[0]
    assert '    void *sp44_copy;\n' in text
    assert '    sp44_copy = scratch.sp44;\n    if ((sp44_copy != NULL)' in text
    assert text.count('scratch.sp44') == 3, 'the store before the if and the call keep the member'


def test_a_member_whose_address_is_taken_inside_the_statement_is_left_alone():
    texts = copied(SOURCE.replace('| 8;', '| 8;\n        fill(arg0, &scratch.sp44, &scratch.count);'))
    assert not texts
