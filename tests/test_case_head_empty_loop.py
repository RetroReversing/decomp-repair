from decomprepair import case_head_empty_loop

SOURCE = '''void draw(Gfx **gfxp, u16 id) {
    switch (obj[id].state) {
    case 1:
        draw_background(gfxp);
        switch (row) {
        case 0:
            break;
        }
        break;
    case 2:
    default:
        obj[id].state++;
        break;
    }
}
'''


def test_the_empty_loop_goes_at_the_head_of_the_arm():
    children = case_head_empty_loop.variants(SOURCE, 'draw')
    assert [family for family, _ in children] == ['case_head_empty_loop']
    assert 'case 1:\n        do { } while (0);\n        draw_background(gfxp);' in children[0][1]


def test_an_arm_that_has_it_is_left_alone():
    source = SOURCE.replace('    case 1:\n', '    case 1:\n        do { } while (0);\n')
    assert case_head_empty_loop.variants(source, 'draw') == []
