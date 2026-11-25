from decomprepair import live_range_retarget_repairs as repair

SOURCE = '''void f(s32 flag, s32 word)
{
    s32 low;
    s32 limit;
    s32 i;
    low = flag;
    if (low == 0)
    {
        g();
    }
    limit = 8;
    i = 0;
    do
    {
        low = word & 0xFFFFFF;
        h(low);
        i += 1;
    }
    while (i < limit);
}
'''


def test_the_first_range_is_written_through_a_free_local():
    found = [text for family, text in repair.variants(SOURCE, 'f')]
    mine = [t for t in found if 'limit = flag;\n    if (limit == 0)' in t]
    assert mine
    # only that range moves: the one that feeds the call keeps the name
    assert all('        low = word & 0xFFFFFF;\n        h(low);' in t for t in mine)
    assert 'i = flag;\n    if (i == 0)' in ''.join(found)


def test_a_local_with_one_value_or_a_local_still_read_afterwards_is_left_alone():
    once = SOURCE.replace('        low = word & 0xFFFFFF;\n', '        low += 1;\n')
    assert not repair.variants(once, 'f')
    # `limit` holds 8 from before the first range until the loop reads it, so it is not free there
    busy = SOURCE.replace('    low = flag;\n', '    limit = 8;\n    low = flag;\n').replace('    limit = 8;\n    i = 0;\n', '    i = 0;\n')
    assert not [t for _, t in repair.variants(busy, 'f') if 'limit = flag' in t]


CLAMP = '''void g(s32 *out, s32 count) {
    s32 alpha;
    s32 r;
    s32 i;

    alpha = out[0] * 3;
    if (alpha < 0) {
        alpha = 0;
    }
    if (alpha >= 0x100) {
        alpha = 0xFF;
    }
    r = out[1];
    for (i = 0; i < count; i++) {
        out[i] = alpha * r;
    }
}
'''


def test_a_value_that_meets_another_at_a_join_or_is_read_later_keeps_its_local():
    # a clamp's `alpha = 0;` reaches the next `if` through a join and the loop reads the clamped value: retargeting
    # it to `r` would leave `alpha` unclamped (a 516-instruction particle renderer, SN GCC 2.8.1, got such a child)
    found = [text for _, text in repair.variants(CLAMP, 'g')]
    assert not any('r = 0;' in t or 'r = 0xFF;' in t or 'r = out[0] * 3;' in t for t in found)
