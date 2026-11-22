from decomprepair.lockstep_pointer_fold import FAMILY, variants

SOURCE = '''s32 release(s32 id)
{
    char *rec;
    void *field;
    u16 **slot;
    u16 head;
    s32 hit;
    slot = (u16 **) table;
    rec = (char *) (*slot);
    head = *((u16 *) rec);
    if (head != 0xFFFF)
    {
        if (count)
        {
            field = rec + 2;
        }
        else
        {
            field = rec + 2;
        }
        do
        {
            if (head == id)
            {
                *((u16 *) (((char *) field) + 0)) = *((u16 *) (((char *) field) + 0)) - 1;
                hit = *((s32 *) (((char *) field) + 2));
            }
            rec += 0x1C;
            head = *((u16 *) rec);
            field += 0x1C;
        }
        while (head != 0xFFFF);
    }
    return hit;
}
'''


def folded(source=SOURCE):
    return [text for family, text in variants(source, 'release') if family == FAMILY]


def test_the_second_pointer_becomes_an_offset_from_the_first():
    plain, emptied = folded()
    assert plain.count('((void *) (rec + 2))') == 3
    assert 'field +=' not in plain and 'field = rec + 2;' not in plain
    assert 'rec += 0x1C;\n            head = *((u16 *) rec);\n        }' in plain


def test_the_if_two_identical_sets_leave_empty_goes_in_a_variant_of_its_own():
    plain, emptied = folded()
    assert 'if (count)' in plain
    assert 'if (count)' not in emptied
    assert emptied.replace('        \n', '') != plain


def test_a_read_between_the_two_steps_stays():
    assert not folded(SOURCE.replace('head = *((u16 *) rec);\n            field += 0x1C;', 'head = *((u16 *) field);\n            field += 0x1C;'))


def test_steps_of_different_size_stay():
    assert not folded(SOURCE.replace('field += 0x1C;', 'field += 0x18;'))


def test_a_second_pointer_read_after_the_loop_stays():
    assert not folded(SOURCE.replace('return hit;', 'return *((s32 *) field);'))


def test_pointees_of_different_size_stay():
    assert not folded(SOURCE.replace('void *field;', 'u16 *field;'))


def test_a_set_that_is_not_an_offset_of_the_walking_pointer_stays():
    assert not folded(SOURCE.replace('field = rec + 2;\n        }\n        else', 'field = rec;\n        }\n        else'))
