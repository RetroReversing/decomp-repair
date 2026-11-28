from decomprepair import loop_argument_scope as scope

HEADER = 'extern void *gImage;\n'
SOURCE = '''void f(void) {
    s32 x;
    s32 y;

    y = 0;
    while (1) {
        if (y >= 8) break;
        x = 0;
        while (1) {
            if (x >= 10) break;
            load(gList++, gImage, x, y);
            rect(gList++, x * 4, x << 5, y << 5);
            x++;
        }
        y++;
    }
}
'''


def test_every_statement_gets_its_block_in_one_child():
    texts = [text for _, text in scope.variants(SOURCE, 'f', HEADER)]
    both = texts[0]
    assert 'void *gImage_held = gImage;' in both
    assert 'load(gList++, gImage_held, x, y);' in both
    assert 's32 x_shift = x << 5;' in both
    assert 's32 y_shift = y << 5;' in both
    assert 'rect(gList++, x * 4, x_shift, y_shift);' in both
    assert both.count('{') == both.count('}') == SOURCE.count('{') + 2


def test_single_statement_children():
    texts = [text for _, text in scope.variants(SOURCE, 'f', HEADER)]
    assert any('gImage_held' in text and 'x_shift' not in text for text in texts)
    assert any('x_shift' in text and 'gImage_held' not in text for text in texts)


def test_nothing_outside_a_loop_or_for_a_written_name():
    assert not scope.variants('void f(s32 a) { load(a << 2, gImage); }', 'f', HEADER)
    assert not scope.variants('void f(s32 a) { do { load(a++, a << 2); } while (a < 4); }', 'f', HEADER)


def test_an_extern_scalar_of_the_file_is_held_too():
    source = 'extern s32 gFlags;\n' + SOURCE.replace('gImage, x', 'gFlags, x')
    assert any('s32 gFlags_held = gFlags;' in text for _, text in scope.variants(source, 'f'))


def test_a_parameter_that_shadows_a_header_name_is_not_a_global():
    source = SOURCE.replace('void f(void)', 'void f(void *gImage)')
    assert not any('gImage_held' in text for _, text in scope.variants(source, 'f', HEADER))
