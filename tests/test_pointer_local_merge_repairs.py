from decomprepair import pointer_local_merge_repairs as repair

SOURCE = '''void f(void **table, s32 n, s32 flags)
{
    void *item;
    void *pick;
    void *keep;
    s32 i;
    i = 0;
    keep = table[0];
    do
    {
        item = table[i];
        if (item != 0)
        {
            g(item);
        }
        if (flags & 1)
        {
            pick = table[0];
        }
        else
        {
            pick = table[n - 1];
        }
        h(pick, keep);
        i += 1;
    }
    while (i < n);
}
'''


def test_the_second_pointer_is_written_as_the_first_and_its_declaration_goes():
    found = [text for family, text in repair.variants(SOURCE, 'f')]
    merged = next(t for t in found if 'void *pick;' not in t and 'void *item;' in t)
    assert 'item = table[0];' in merged and 'h(item, keep);' in merged
    assert 'pick' not in merged


def test_a_pointer_carried_round_a_loop_or_one_whose_address_is_taken_is_left_alone():
    carried = SOURCE.replace('        item = table[i];\n', '        g(item);\n        item = table[i];\n')
    assert not [t for _, t in repair.variants(carried, 'f') if 'void *item;' in t and 'void *pick;' not in t]
    address = SOURCE.replace('        h(pick, keep);\n', '        h(&pick, keep);\n')
    assert not [t for _, t in repair.variants(address, 'f') if 'pick' not in t]
