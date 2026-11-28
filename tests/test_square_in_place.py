from decomprepair import square_in_place

SOURCE = '''void func(s16 *a, s16 *b) {
    s32 dx;
    s32 dy;

    dx = a[0] - b[0];
    dy = a[1] - b[1];
    if (length(((u32) (dx * dx) >> 12) + ((u32) (dy * dy) >> 12)) < 5) {
        hit(a);
    }
}
'''


def test_both_squares_then_each():
    children = [child for _, child in square_in_place.variants(SOURCE, 'func')]
    assert len(children) == 3
    assert '    dx *= dx;\n    dy *= dy;\n    if (length(((u32) dx >> 12) + ((u32) dy >> 12)) < 5) {' in children[0]


def test_a_local_read_later_or_in_a_loop_is_left_alone():
    assert len(square_in_place.variants(SOURCE.replace('hit(a);', 'hit(dx);'), 'func')) == 1
    looped = SOURCE.replace('    dx = a[0]', '    while (a) {\n    dx = a[0]').replace('        hit(a);\n    }\n', '        hit(a);\n    }\n    }\n')
    assert not square_in_place.variants(looped, 'func')


SHIFTED = '''void func(s16 *a, s16 *b) {
    u32 dx;
    s32 dy;

    dx = a[0] - b[0];
    dx = (u32) (dx * dx) >> 12;
    dy = a[1] - b[1];
    dy = (u32) (dy * dy) >> 12;
    use(dx + dy);
}
'''


def test_a_shifted_self_square_is_two_updates_all_sites_first():
    children = [child for _, child in square_in_place.variants(SHIFTED, 'func')]
    assert len(children) == 3
    assert '    dx *= dx;\n    dx >>= 12;\n' in children[0]
    # a signed local keeps the logical shift
    assert '    dy *= dy;\n    dy = (u32) dy >> 12;\n' in children[0]
