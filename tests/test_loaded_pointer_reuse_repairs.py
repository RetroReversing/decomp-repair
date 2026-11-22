from decomprepair import loaded_pointer_reuse_repairs as repair

SOURCE = '''void f(void *list, s32 *flag, s32 n)
{
    void *held;
    void *other;
    s32 i;
    i = 0;
    do
    {
        held = *((void **) (((char *) list) + 0x6C));
        *((s32 *) (((char *) held) + 0x2C)) = n;
        other = list;
        *((s32 *) (((char *) (*((void **) (((char *) other) + 0x6C)))) + 0x24)) = *flag;
        *((s8 *) (((char *) (*((void **) (((char *) other) + 0x6C)))) + 0x32)) = (s8) n;
        i += 1;
    }
    while (i < n);
}
'''


def test_later_loads_of_the_same_field_go_through_the_local():
    found = [text for family, text in repair.variants(SOURCE, 'f')]
    assert len(found) == 3
    first, second, both = found
    assert 'held = *((void **) (((char *) other) + 0x6C));\n        *((s32 *) (((char *) held) + 0x24)) = *flag;' in first
    assert '(*((void **)' in first
    assert 'held = *((void **) (((char *) other) + 0x6C));\n        *((s8 *) (((char *) held) + 0x32)) = (s8) n;' in second
    assert '(*((void **)' not in both
    assert both.count('held = *((void **)') == 3


def test_a_local_read_before_it_is_assigned_in_its_block_is_left_alone():
    stale = SOURCE.replace('        held = *((void **) (((char *) list) + 0x6C));\n', '').replace(
        '    i = 0;\n', '    held = *((void **) (((char *) list) + 0x6C));\n    i = 0;\n')
    assert not repair.variants(stale, 'f')
