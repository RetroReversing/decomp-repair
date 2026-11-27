from decomprepair import narrow_value_in_counter

SOURCE = '''void draw(Gfx **gfxp, u16 id) {
    s32 i;
    s32 j;
    u16 c;

    switch (id) {
    case 1:
        if (id) {
            c = 0xFF;
        } else {
            c = 0x80;
        }
        set_colour(gfxp, c, c, c);
        for (i = 0; i < 6; i++) {
            for (j = 0; j < 15; j++) {
                text[j] = i + j;
            }
        }
        break;
    }
}
'''


def test_the_colour_moves_into_the_counter_that_is_free():
    children = narrow_value_in_counter.variants(SOURCE, 'draw')
    texts = [text for _, text in children]
    assert any('j = 0xFF;' in text and 'set_colour(gfxp, (u16)j, (u16)j, (u16)j);' in text
               and 'u16 c;' not in text for text in texts)
    assert children[0][0] == 'narrow_value_in_counter'


def test_a_counter_read_after_is_not_taken():
    source = SOURCE.replace('        break;', '        keep(j);\n        break;').replace(
        'set_colour(gfxp, c, c, c);', 'j = 3;\n        set_colour(gfxp, c, c, c);')
    assert not any('j = 0xFF;' in text for _, text in narrow_value_in_counter.variants(source, 'draw'))


def test_a_value_read_before_it_is_set_is_left_alone():
    source = SOURCE.replace('    switch (id) {', '    keep(c);\n    switch (id) {')
    assert narrow_value_in_counter.variants(source, 'draw') == []
