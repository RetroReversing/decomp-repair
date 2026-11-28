"""arm_constant_run_shift: a group of constant assignments moved within its run in every arm at once."""
from decomprepair import arm_constant_run_shift as shift
from decomprepair import registry

ARM = '''        x0 = {x};
        y0 = 3;
        r = 0xFF;
        g = 0;
        y1 = -3;
        y2 = {x};
'''
SOURCE = ('void f(s32 type) {\n    s16 x0, y0;\n    s16 y1;\n    s16 y2;\n    u8 r;\n    u8 g;\n\n'
          '    if (type == 0) {\n' + ARM.format(x=-5) + '        use(1);\n    } else if (type == 1) {\n'
          + ARM.format(x=-15) + '    }\n    draw(x0, y0, y1, y2, r, g);\n}\n')


def texts(source):
    return [text for _family, text in shift.variants(source, 'f')]


def order(text):
    return [line.split('=')[0].strip() for line in text.split('\n') if line.startswith('        ') and '=' in line]


def test_the_colours_move_below_the_corners_in_both_arms_at_once():
    want = ['x0', 'y0', 'y1', 'y2', 'r', 'g'] * 2
    child = next(text for text in texts(SOURCE) if order(text) == want)
    assert 'x0 = -5;' in child and 'x0 = -15;' in child and 'y2 = -15;' in child
    assert sorted(child.split('\n')) == sorted(SOURCE.split('\n'))


def test_an_arm_without_one_of_the_names_still_moves_the_rest():
    source = SOURCE.replace('        g = 0;\n', '        g = 0;\n        b = 0;\n', 1)
    source = source.replace('    u8 g;\n', '    u8 g;\n    u8 b;\n')
    want = ['x0', 'y0', 'y1', 'y2', 'r', 'g', 'b', 'x0', 'y0', 'y1', 'y2', 'r', 'g']
    assert any(order(text) == want for text in texts(source))


def test_globals_volatiles_and_address_taken_locals_stay():
    for source in (SOURCE.replace('    u8 r;\n    u8 g;\n', ''),
                   SOURCE.replace('    u8 r;\n    u8 g;\n', '    volatile u8 r;\n    volatile u8 g;\n'),
                   SOURCE.replace('draw(x0, y0, y1, y2, r, g);', 'draw(x0, y0, y1, y2, &r, &g);')):
        for text in texts(source):
            assert [n for n in order(text)].index('r') == 2


def test_a_repeated_name_ends_the_run():
    source = 'void f(void) {\n    s32 a;\n    s32 b;\n\n    a = 1;\n    a = 2;\n    use(a, b);\n}\n'
    assert texts(source) == []


def test_it_is_registered():
    assert shift.FAMILY in {family for item in registry.declared() for family in item.families}


def test_a_much_longer_run_is_not_taken_for_an_arm():
    extra = ['p', 'q', 's', 't']
    init = ''.join(f'    {n} = 0;\n' for n in extra + ['x0', 'y0', 'r', 'g', 'y1', 'y2'])
    declare = ''.join(f'    s32 {n};\n' for n in extra)
    source = SOURCE.replace('    u8 g;\n\n', '    u8 g;\n' + declare + '\n' + init)
    children_ = texts(source)
    assert children_ and all(init in text for text in children_)
