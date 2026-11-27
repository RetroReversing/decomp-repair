from decomprepair.stride_element_read import variants

SOURCE = """extern char steps[];
extern s32 gStep;

void step(u16 pad) {
    if (pad & *(s32 *)((gStep * 2) + steps)) {
        gStep++;
    }
}
"""


def test_a_byte_table_read_at_a_halfword_stride_becomes_a_halfword_table():
    children = [text for _, text in variants(SOURCE, 'step')]
    assert len(children) == 2
    assert 'extern u16 steps[];' in children[0] and 'pad & steps[gStep]' in children[0]
    assert 'extern s16 steps[];' in children[1]


def test_a_table_with_other_uses_is_subscripted_through_a_cast():
    source = SOURCE.replace('gStep++;', 'use(steps);')
    child = variants(source, 'step')[0][1]
    assert 'extern char steps[];' in child and '((u16 *)steps)[gStep]' in child


def test_a_read_as_wide_as_its_stride_and_a_store_are_left_alone():
    assert variants(SOURCE.replace('*(s32 *)', '*(u16 *)'), 'step') == []
    assert variants(SOURCE.replace('gStep++;', '*(s32 *)((gStep * 2) + steps) = 0;').replace(
        'pad & *(s32 *)((gStep * 2) + steps)', 'pad'), 'step') == []
    assert variants(SOURCE.replace('pad & *(s32 *)', 'use(&*(s32 *)').replace('+ steps))', '+ steps)))'), 'step') == []
