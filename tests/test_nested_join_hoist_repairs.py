from decomprepair.nested_join_hoist_repairs import FAMILY, variants

SOURCE = '''void f(s32 k, s32 a, s32 b)
{
    s32 v;
    s32 r;
    switch (k)
    {
        case 1:
            if (a == 0) {
                if (b != 0) {
                    v = first();
block_1:
                    if (v == 0) {
                        goto block_2;
                    }
                } else {
                    r = second();
block_2:
                    third(r);
                }
            }
            break;
        case 2:
            if (a != 0) {
                if (b == 0) {
                    goto block_2;
                }
                v = other();
                goto block_1;
            }
            break;
        case 3:
            fourth();
            break;
    }
}
'''


def flat(text):
    return ' '.join(text.split())


def moved(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_nested_tails_follow_the_last_arm_that_jumps_to_them():
    text = [t for t in moved() if t.index('block_1:') > t.index('case 2:')][0]
    first_arm = flat(text.split('case 2:')[0])
    # the nest keeps only gotos
    assert 'v = first(); goto block_1; } else { r = second(); goto block_2; }' in first_arm
    assert 'block_1:' not in first_arm and 'block_2:' not in first_arm
    # the tails sit before the next arm; the first one that only jumped to the second falls into it
    tail = flat(text[text.index('block_1:'):text.index('case 3:')])
    assert tail == 'block_1: if (v != 0) { break; } block_2: third(r); break;'


def test_the_tails_can_also_follow_the_arm_that_held_them():
    text = [t for t in moved() if t.index('block_1:') < t.index('case 2:')][0]
    assert flat(text[text.index('block_1:'):text.index('case 2:')]) == 'block_1: if (v != 0) { break; } block_2: third(r); break;'


def test_a_label_no_other_arm_jumps_to_stays_where_it_is():
    own = SOURCE.replace('''            if (a != 0) {
                if (b == 0) {
                    goto block_2;
                }
                v = other();
                goto block_1;
            }
''', '''            if (a != 0) {
                fifth();
            }
''')
    assert not moved(own)


def test_an_arm_that_does_more_after_the_nest_is_left_alone():
    longer = SOURCE.replace('            }\n            break;\n        case 2:', '            }\n            after();\n            break;\n        case 2:')
    assert not moved(longer)
