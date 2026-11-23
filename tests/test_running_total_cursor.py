"""A size summed into an allocation call and the cursor chain after it, kept in one variable."""
import re

from decomprepair.running_total_cursor import FAMILY, variants

CODE = '''typedef int s32;
void *alloc(s32, s32);
void fill(void *obj, s32 a, s32 b)
{
    void *p;
    void *q1;
    void *q2;
    s32 x;
    if (obj)
    {
        x = a * 4;
        p = alloc((((x + 0xB8) + x) + b) + b, 0x21);
        if (p != 0)
        {
            q1 = p + 0xB8;
            *(void **) (obj + 0x54) = q1;
            q2 = q1 + x;
            *(void **) (obj + 0x58) = q2;
            *(void **) (obj + 0x5C) = q2 + b;
        }
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_sum_and_the_cursor_chain_use_one_variable():
    children = variants(CODE, 'fill')
    assert [family for family, _ in children] == [FAMILY] * 3
    both, chain, total = (squash(text) for _, text in children)
    assert 'p = (__typeof__ (p)) 0xB8; p += x; p += x; p += b; p = alloc(p + b, 0x21);' in both or \
        'p = (__typeof__ (p)) 0xB8; x = a * 4;' in both
    assert 'p += 0xB8; *(void **) (obj + 0x54) = p; p += x; *(void **) (obj + 0x58) = p;' in both
    assert 'q1' not in both and 'q2' not in both
    assert 'q1' not in chain and '(__typeof__' not in chain and 'p = alloc((((x + 0xB8) + x) + b) + b, 0x21);' in chain
    assert '(__typeof__ (p)) 0xB8' in total and 'q1 = p + 0xB8;' in total


def test_a_temporary_used_after_the_next_link_or_inside_a_loop_is_left_alone():
    shared = squash(variants(CODE.replace('*(void **) (obj + 0x5C) = q2 + b;', '*(void **) (obj + 0x5C) = q1;'), 'fill')[1][1])
    assert 'p += 0xB8;' in shared and 'q2 = p + x;' in shared  # (q1 is read after the next link: that link stays)
    looped = CODE.replace('q1 = p + 0xB8;', 'while (b--) { q1 = p + 0xB8; }')
    assert all('p += 0xB8' not in text for _, text in variants(looped, 'fill'))
    assert variants(CODE.replace('alloc((((x + 0xB8) + x) + b) + b, 0x21)', 'alloc(x + b, 0x21)'), 'fill')[0][1].count('(__typeof__') == 0
