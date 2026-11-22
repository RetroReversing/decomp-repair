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
