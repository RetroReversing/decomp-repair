from decomprepair.entry_parameter_copy_repairs import variants

SOURCE = """void render(Cam *arg0, s32 arg1) {
    f32 scale;
    do {
        scale = arg0->zoom;
        if (arg0->flags & 4) {
            use(arg1, scale);
        }
        use(arg1 * 2, scale);
    } while (0);
}
"""


def _copies(source, param='arg1'):
    return [c for family, c in variants(source, 'render') if family == 'entry_parameter_copy' and f'{param}_in)' in c]


def test_a_parameter_is_copied_into_a_local_after_the_first_statement():
    found = _copies(SOURCE)
    assert any('scale = arg0->zoom;\n  arg1 = arg1_in;' in c for c in found)
    assert all('s32 arg1_in)' in c and '  s32 arg1;' in c and 'use(arg1, scale)' in c for c in found)


def test_the_copy_is_offered_at_the_top_of_the_body_and_inside_the_wrapper():
    places = {c.index('arg1 = arg1_in;') for c in _copies(SOURCE)}
    assert len(places) == 3  # past the declarations, inside the do-while, after its first statement


def test_a_parameter_used_once_or_addressed_is_left_alone():
    once = SOURCE.replace('use(arg1 * 2, scale);', 'use(2, scale);')
    assert not _copies(once)
    addressed = SOURCE.replace('use(arg1, scale);', 'use(&arg1, scale);')
    assert not _copies(addressed)


def test_a_function_without_parameters_or_with_asm_gives_nothing():
    assert not variants('void f(void) { g(); }\n', 'f')
    assert not variants(SOURCE.replace('scale = arg0->zoom;', 'asm("nop");'), 'render')
