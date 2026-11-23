from decomprepair.disjoint_local_merge_repairs import FAMILY, variants

SOURCE = '''void f(s32 n)
{
    s32 var_s7;
    s32 var_s7_3;
    s32 other;
    var_s7 = 0;
    do {
        step(var_s7);
        var_s7 += 1;
    } while (var_s7 < n);
    var_s7_3 = 0;
    do {
        more(var_s7_3);
        var_s7_3 += 1;
    } while (var_s7_3 < n);
}
'''


def merged(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_later_counter_takes_the_earlier_name():
    first = merged()[0]
    assert 'var_s7_3' not in first
    assert 'var_s7 = 0;\n    do {\n        more(var_s7);' in first
    assert first.count('var_s7 += 1;') == 2


def test_a_counter_still_read_after_the_second_loop_is_not_renamed():
    texts = merged(SOURCE.replace('} while (var_s7_3 < n);\n}', '} while (var_s7_3 < n);\n    last(var_s7);\n}'))
    assert not [t for t in texts if 'var_s7_3' not in t]


def test_loops_that_share_a_nest_are_not_merged():
    nested = '''void f(s32 n)
{
    s32 a;
    s32 b;
    a = 0;
    do {
        b = 0;
        do {
            step(a, b);
            b += 1;
        } while (b < n);
        a += 1;
    } while (a < n);
}
'''
    assert not merged(nested)


ARMS = '''void f(u8 *text, s32 n)
{
    u32 color;
    s32 index;
    s32 i;
    i = 0;
    do
    {
        switch (text[i])
        {
            case 5:
                color = table[text[i + 1]];
                put(color >> 24, color);
                break;
            case 7:
                color = table[text[i + 1] & 0xF];
                put(color >> 24, color);
                break;
            default:
                index = text[i] - 0x21;
                draw(index);
                break;
        }
        i += 1;
    }
    while (i < n);
}
'''


def test_a_colour_word_and_an_index_of_different_signedness_share_one_variable_inside_a_loop():
    texts = merged(ARMS)
    assert texts, 'the pair sits in one loop body but each is assigned before it is read: it stays'
    shared = [t for t in texts if 'index' not in t]
    assert len(shared) == 2
    kept_early = [t for t in shared if 'u32 color;' in t]
    kept_late = [t for t in shared if 's32 color;' in t]
    assert kept_early and kept_late, 'once with the earlier type and once with the later one'
    assert all('color = text[i] - 0x21;' in t and 'draw(color);' in t for t in shared)


def test_a_later_local_read_before_it_is_assigned_in_the_loop_is_not_merged():
    carried = ARMS.replace('index = text[i] - 0x21;\n                draw(index);', 'draw(index);\n                index = text[i] - 0x21;')
    assert not merged(carried)


def test_only_word_sized_integer_types_are_exchanged():
    narrow = ARMS.replace('s32 index;', 's16 index;')
    assert not merged(narrow)


CROSS = '''u32 f(s32 size, s32 tag, s32 mask)
{
    if (tag == 45) {
        return 0;
    } else {
        u32 temp;
        u32 inverse;
        u32 start;
        temp = gBottom + mask;
        inverse = ~mask;
        start = inverse & temp;
        return start;
    }
    while (size != 0) {
        u32 extra;
        extra = size & mask;
        size -= extra;
    }
    return 1;
}
'''


def test_a_merge_across_blocks_declares_the_survivor_for_the_whole_function():
    from decomprepair.disjoint_local_merge_repairs import SWAP_FAMILY
    found = [(family, text) for family, text in variants(CROSS, 'f') if 'extra' not in text and 'temp = ' in text
             and 'size & mask' in text]
    merged = [text for family, text in found if family == FAMILY and 'temp = size & mask;' in text]
    assert merged, found
    assert merged[0].startswith('u32 f(s32 size, s32 tag, s32 mask)\n{\n    u32 temp;\n')
    assert '        u32 temp;\n' not in merged[0]
    swapped = [text for family, text in found if family == SWAP_FAMILY and 'temp = size & mask;' in text]
    assert swapped and 'start = temp & inverse;' in swapped[0]


def test_a_binary_and_with_a_local_is_not_an_address():
    from decomprepair.integer_repair_support import _address_taken
    assert not _address_taken('x = y & n;', 'n')
    assert not _address_taken('x = a[i] & n;', 'n')
    assert not _address_taken('x = (a + b) & n;', 'n')
    assert not _address_taken('if (a && n)', 'n')
    assert _address_taken('f(&n);', 'n')
    assert _address_taken('p = (u32 *)&n;', 'n')
    assert _address_taken('x = (s32)&n;', 'n')
    assert _address_taken('return &n;', 'n')


def test_a_loop_local_flag_is_offered_a_merge_with_a_value_far_after_the_loop():
    names = "n0..n4"
    decls = '\n'.join(f'    s32 n{i};' for i in range(5))
    uses = '\n'.join(f'    n{i} = F({i}); G(n{i});' for i in range(5))
    src = f"""void f(s32 k, s32 limit) {{
    s32 flag;
    s32 temp;
{decls}
    s32 i;
    i = 0;
    do
    {{
        flag = 0;
        if (k > i)
        {{
            flag = 1;
        }}
        if (flag != 0)
        {{
            H(i);
        }}
        i += 1;
    }}
    while (i < limit);
{uses}
    temp = F(k);
    G(temp);
}}
"""
    out = [text for _, text in variants(src, 'f')]
    assert any('temp = F(k);' not in text and 'flag = F(k);' in text for text in out), names


WIDTHS = '''void f(void *p)
{
    long flag;
    char flag2;
    s32 mask;
    flag = 0;
    if (check(p)) {
        flag = 1;
    }
    mask = flag & 3;
    flag2 = mask;
    if (flag2 != 0) {
        flag2 = 0;
        if (more(p)) {
            flag2 = 1;
        }
    }
    use(p, flag2);
}
'''


def test_a_long_flag_and_the_char_that_follows_it_are_one_variable():
    # m2c typed the flag `long` and the value derived from it `char`; the game had one variable, so the second
    # name's pseudo joins the first's long one (a saved-register order that two short pseudos cannot give)
    texts = merged(WIDTHS)
    assert [t for t in texts if 'flag2' not in t and 'long flag;' in t]
    kept = [t for t in texts if 'flag2' not in t and 'long flag;' in t][0]
    assert 'use(p, flag);' in kept and 'mask = flag & 3;' in kept
    assert 'char flag;' in [t for t in texts if 'flag2' not in t][-1] or len([t for t in texts if 'flag2' not in t]) == 1


def test_a_long_flag_read_after_the_second_name_starts_is_not_merged():
    texts = merged(WIDTHS.replace('use(p, flag2);', 'use(p, flag2);\n    last(flag);'))
    assert not [t for t in texts if 'flag2' not in t]
