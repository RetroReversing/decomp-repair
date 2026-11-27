"""A word symbol indexed by m2c's byte step: the element index and the byte-offset cast."""
from decomprepair import symbol_byte_index_same_size as m

SOURCE = '''typedef int s32;
typedef float f32;
typedef unsigned short u16;
extern f32 D_80122530;
extern u16 D_80122540;
s32 g(s32);

void f(s32 arg0, s32 best) {
    *(&D_80122530 + (g(arg0) * 4)) = (f32) best;
}
'''


def test_a_word_symbol_gets_the_element_index_and_the_byte_cast():
    children = m.variants(SOURCE, 'f')
    assert [family for family, _ in children] == [m.FAMILY, m.FAMILY]
    assert '*(&D_80122530 + (g(arg0))) = (f32) best;' in children[0][1]
    assert '*(f32 *)((s8 *)&D_80122530 + (g(arg0) * 4)) = (f32) best;' in children[1][1]


def test_a_shifted_step_a_plain_index_and_a_narrower_symbol_are_handled():
    shifted = SOURCE.replace('(g(arg0) * 4)', '(arg0 << 2)')
    assert '*(&D_80122530 + arg0) = ' in m.variants(shifted, 'f')[0][1]
    # a step wider than the element is narrow_table_byte_offset's, a step that is no power of two nobody's
    assert m.variants(SOURCE.replace('D_80122530 +', 'D_80122540 +'), 'f') == []
    assert m.variants(SOURCE.replace('* 4', '* 12'), 'f') == []


def test_a_half_word_step_on_a_word_symbol_is_only_a_byte_cast():
    children = m.variants(SOURCE.replace('* 4', '* 2'), 'f')
    assert len(children) == 1 and '(s8 *)&D_80122530 + (g(arg0) * 2)' in children[0][1]
