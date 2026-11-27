"""A byte pointer plus a byte index under a pointer cast, as an integer sum with the index first."""
from decomprepair import byte_pointer_sum_int_first as m

SOURCE = '''typedef signed char s8;
typedef unsigned char u8;
typedef int s32;
typedef unsigned short u16;
extern u8 D_800B2DB2[];
extern char D_800B2DA8[];

void f(s32 arg0, u16 *arg1) {
    s32 off;
    s32 idx;
    char *base;

    off = arg0 * 12;
    idx = D_800B2DB2[off] * 4;
    base = D_800B2DA8 + off;
    *(u16 *)(*(s32 *)(base + idx) + 0x10) = arg1[0];
}
'''


def test_the_index_comes_first_in_an_integer_sum_and_the_other_order_is_offered():
    children = m.variants(SOURCE, 'f')
    assert [family for family, _ in children] == [m.FAMILY, m.FAMILY]
    assert '*(s32 *)(idx + (s32) base)' in children[0][1]
    assert '*(s32 *)((s32) base + idx)' in children[1][1]


def test_word_pointers_calls_and_assignments_are_left_alone():
    word = SOURCE.replace('char *base;', 's32 *base;').replace('char D_800B2DA8[]', 's32 D_800B2DA8[]')
    assert m.variants(word, 'f') == []
    assert m.variants(SOURCE.replace('(base + idx)', '(base + g(idx))'), 'f') == []
    assert m.variants(SOURCE.replace('(base + idx)', '(base + (idx = 4))'), 'f') == []


def test_a_shifted_index_is_parenthesised_and_several_sites_give_an_all_child():
    source = SOURCE.replace('    *(u16 *)(', '    *(u16 *)(*(s32 *)(base + (idx << 2)) + 0x12) = arg1[1];\n    *(u16 *)(')
    children = m.variants(source, 'f')
    assert len(children) == 6
    assert '((idx << 2) + (s32) base)' in children[2][1]
    assert children[2][1].count('(s32) base') == 2
